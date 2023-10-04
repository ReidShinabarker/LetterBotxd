# recommend.py

import discord
from discord.ext import commands
import database
from letterboxdpy import user as lb_user
from letterboxdpy import movie as lb_movie


class Recommendation(discord.ui.View):
    def __init__(self, show_ratings):
        super().__init__()
        # slash command Interaction object
        self.initiator: discord.Interaction = None

        # progression states
        self.gathering_info = True
        self.taking_attendance = False
        self.attendance_done = False
        self.recommendations_done = False

        # embed values
        self.embed_desc_gathering = "Recommendation initiated..."
        self.embed_desc_attendance = ""
        self.embed_fields_attendance = [["**PRESENT**", ""], ["**IGNORED**", ""], ["**ABSENT**", ""]]
        self.embed_fields_recommendation = []
        self.poster_link = ""

        # data objects
        self.users = []
        self.movies = {}

        # parameters
        self.show_ratings = show_ratings
        self.limit_per_page = 10

        # variables
        self.apply_to_all = False
        self.lowest_relevant_score = None
        self.active_account_index = 0

    async def initiate(self, initiator: discord.Interaction):
        self.initiator = initiator
        await initiator.response.send_message(embeds=await self.make_embeds())
        await self.find_accounts()

    async def update_response(self):
        await self.initiator.edit_original_response(embeds=await self.make_embeds(),
                                                    view=self if self.taking_attendance else None)

    async def make_embeds(self):
        embeds = []
        if self.recommendations_done:
            recommend_embed = discord.Embed(title="**MOVIE RECOMMENDATIONS**")
            recommend_embed.set_image(url=self.poster_link)
            for field in self.embed_fields_recommendation:
                recommend_embed.add_field(name=field[0], value=field[1])
            embeds.append(recommend_embed)

        if self.gathering_info:
            info_embed = discord.Embed(title="**MOVIE RECOMMENDATIONS**",
                                       description=self.embed_desc_gathering)
            embeds.append(info_embed)

        if self.taking_attendance or self.attendance_done:
            description = self.users[self.active_account_index][1].mention if not self.attendance_done else None
            attendance_embed = discord.Embed(title="**ATTENDANCE**",
                                             description=description)
            for field in self.embed_fields_attendance:
                attendance_embed.add_field(name=field[0], value=field[1])
            embeds.append(attendance_embed)

        return embeds

    async def find_accounts(self):
        cursor = await database.get_cursor()
        cursor.execute(f"SELECT users.member, users.account FROM users, memberships WHERE "
                       f"memberships.member=users.member AND memberships.guild='{self.initiator.guild_id}'")

        self.embed_desc_gathering += f"\nFinding linked Letterboxd accounts..."
        await self.update_response()

        for item in cursor:
            # [letterboxdpy User object, discord.Member Object, Attendance value]
            self.users.append([lb_user.User(str(item[1])), self.initiator.client.get_user(int(item[0])), None])

        cursor.close()
        self.taking_attendance = True
        self.embed_desc_gathering += f"\nWaiting for attendance to be finished..."
        await self.update_response()

    async def collect_movies(self):
        self.embed_desc_gathering += f"\nCollecting movies in watchlists..."
        await self.update_response()
        for user in self.users:
            attendance = user[2]
            # if ignored
            if attendance == 1:
                continue
            for movie in lb_user.user_films_on_watchlist(user[0]):
                # if present else absent
                value = 2 if attendance == 0 else -2

                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + value
                else:
                    self.movies[movie] = value

        await self.check_watched()

    async def check_watched(self):
        self.embed_desc_gathering += f"\nChecking which movies have already been seen by people..."
        await self.update_response()
        for user in self.users:
            attendance = user[2]
            # if ignored
            if attendance == 1:
                continue
            for movie in lb_user.user_films_watched(user[0]):
                # if present else absent
                value = -1 if attendance == 0 else 1

                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + value

        sorted_movies = sorted(self.movies.items(), key=lambda x: (-x[1], x[0]))

        # find the lowest score of the x number of movies that are going to be recommended
        # to know how many ratings need to be looked up
        self.lowest_relevant_score = sorted_movies[self.limit_per_page-1][1]

        # convert back to dict to be easier to work with
        self.movies = dict(sorted_movies)

        if self.show_ratings:
            await self.check_ratings()
        else:
            await self.calculate_recommendation()

    async def check_ratings(self):
        self.embed_desc_gathering += f"\nObjectively calculating how good each movie is..."
        await self.update_response()

        # find the average rating for each recommendation and add it to the movie tuple
        rated_movies = {}
        for movie in self.movies:
            # can stop looking up ratings if it doesn't have a chance to be recommended anyway
            if self.lowest_relevant_score > self.movies[movie]:
                break
            rating = float(lb_movie.Movie(movie[1]).rating.split()[0])
            rated_movies[(movie[0], movie[1], rating)] = self.movies[movie]

        # sort again, this time using the rating as a tiebreaker
        self.movies = dict(sorted(rated_movies.items(), key=lambda x: (x[1], x[0][2]), reverse=True))

        await self.calculate_recommendation()

    async def calculate_recommendation(self):
        self.embed_desc_gathering += f"\nCalculating recommendations..."
        await self.update_response()

        self.poster_link = ''
        i = 0
        score_column = ''
        title_column = ''
        rating_column = ''
        for movie, score in self.movies.items():
            if i >= self.limit_per_page:
                break
            if self.poster_link == '':
                self.poster_link = lb_movie.movie_poster(movie[1])

            score = f"{score}\n"
            name = f"[{movie[0]}](https://www.letterboxd.com/film/{movie[1]}/)\n"
            rating = ''
            if self.show_ratings:
                rating = f"{movie[2]}\n"
            # field bodies can't go over 1024 characters
            if (len(score) + len(score_column) >= 1024 or
                    len(name) + len(title_column) >= 1024 or
                    len(rating) + len(rating_column) >= 1024):
                break
            score_column += score
            title_column += name
            if self.show_ratings:
                rating_column += f"{'%.2f' % movie[2]}\n"
            i += 1

        self.embed_fields_recommendation = [("SCORE", score_column), ("TITLE", title_column)]
        if self.show_ratings:
            self.embed_fields_recommendation.append(("RATING", rating_column))

        self.gathering_info = False
        self.recommendations_done = True
        await self.update_response()

    async def mark_attendance(self, value):
        working = True
        while working:
            self.users[self.active_account_index][2] = value
            self.embed_fields_attendance[value][1] += f"{self.users[self.active_account_index][1].mention}\n"
            self.active_account_index += 1
            if self.active_account_index >= len(self.users):
                self.attendance_done = True
            if not self.apply_to_all or self.attendance_done:
                working = False

        if self.taking_attendance and self.attendance_done:
            self.taking_attendance = False
            await self.collect_movies()
            return

        await self.update_response()

    @discord.ui.button(label="PRESENT", style=discord.ButtonStyle.green)
    async def present_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.mark_attendance(value=0)

    @discord.ui.button(label="IGNORE", style=discord.ButtonStyle.grey)
    async def ignore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.mark_attendance(value=1)

    @discord.ui.button(label="ABSENT", style=discord.ButtonStyle.red)
    async def absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.mark_attendance(value=2)

    @discord.ui.button(label="🟩 APPLY TO REMAINING", style=discord.ButtonStyle.blurple)
    async def all_button_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator.user:
            await interaction.response.defer()
            return
        self.apply_to_all = not self.apply_to_all
        button.label = ("✅" if self.apply_to_all else "🟩") + " APPLY TO REMAINING"
        await self.update_response()
        await interaction.response.defer()
