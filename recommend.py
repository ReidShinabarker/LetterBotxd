# recommend.py

import discord
from discord.ext import commands
import database
from letterboxdpy import user as lb_user
from letterboxdpy import movie as lb_movie


class RecommendationUser:
    def __init__(self, account: lb_user.User, user: discord.User):
        self.account = account
        self.user = user

        self.attendance_value = None
        self.watchlist = []
        self.watched_movies = []
        self.liked_movies = []

    async def display_user(self):
        mention = self.user.mention
        username = self.account.username
        return f"{mention} - [{username}](https://letterboxd.com/{username}/)"


class Recommendation(discord.ui.View):
    def __init__(self, channel_for_attendance: discord.VoiceChannel, show_ratings):
        super().__init__()
        # slash command Interaction object
        self.initiator: discord.Interaction = None

        # progression states
        self.working_on_recommendations = True
        self.taking_attendance = False
        self.attendance_done = False
        self.recommendations_done = False

        # embed values
        self.embed_desc_gathering = "Recommendation initiated..."
        self.embed_desc_attendance = ""
        self.embed_fields_recommendation = []
        self.poster_link = ""

        # data objects
        self.users = []
        self.present_users = []
        self.ignored_users = []
        self.absent_users = []
        self.movies = {}

        # parameters
        self.attendance_channel = channel_for_attendance
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

        if self.working_on_recommendations:
            info_embed = discord.Embed(title="**RECOMMENDATIONS IN PROGRESS**",
                                       description=self.embed_desc_gathering)
            embeds.append(info_embed)

        if self.taking_attendance or self.attendance_done:
            description = None
            if not self.attendance_done:
                active_user = self.users[self.active_account_index]
                description = (await active_user.display_user())
            attendance_embed = discord.Embed(title="**ATTENDANCE**",
                                             description=description)
            users = ""
            for user in self.present_users:
                users += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**PRESENT**", value=users)

            users = ""
            for user in self.ignored_users:
                users += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**IGNORED**", value=users)

            users = ""
            for user in self.absent_users:
                users += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**ABSENT**", value=users)

            embeds.append(attendance_embed)

        return embeds

    async def find_accounts(self):
        cursor = await database.get_cursor()
        cursor.execute(f"SELECT users.member, users.account FROM users, memberships WHERE "
                       f"memberships.member=users.member AND memberships.guild='{self.initiator.guild_id}'")

        self.embed_desc_gathering += f"\nFinding linked Letterboxd accounts..."
        await self.update_response()

        for item in cursor:
            self.users.append(RecommendationUser(lb_user.User(str(item[1])),
                                                 self.initiator.client.get_user(int(item[0]))))

        cursor.close()

        # if attendance should be automatic
        if self.attendance_channel is not None:
            for user in self.users:
                # if the user is in the voice channel
                if any(member.id == user.user.id for member in self.attendance_channel.members):
                    self.present_users.append(user)
                else:
                    self.absent_users.append(user)

            self.attendance_done = True
            await self.mark_attendance()

        # else the attendance will be manual
        else:
            self.taking_attendance = True
            self.embed_desc_gathering += f"\nPlease manually take attendance..."
            await self.update_response()

    async def collect_movies(self):
        self.embed_desc_gathering += f"\nCollecting movies in watchlists and those that have already been seen..."
        await self.update_response()

        for user in self.users:
            user.watchlist = lb_user.user_films_on_watchlist(user.account)
            user.watched_movies = lb_user.user_films_watched(user.account)
            user.liked_movies = []

        await self.apply_scoring()

    async def apply_scoring(self):
        self.embed_desc_gathering += f"\nApplying the scoring rules to the movies eligible for recommendation..."
        await self.update_response()

        # apply scoring for present users
        for user in self.present_users:
            for movie in user.watchlist:
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + 2
                else:
                    self.movies[movie] = 2
            for movie in user.watched_movies:
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + -1
                else:
                    self.movies[movie] = -1
            for movie in user.liked_movies:
                pass

        # apply scoring for absent users
        for user in self.absent_users:
            for movie in user.watchlist:
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + -2
                else:
                    self.movies[movie] = -2
            for movie in user.watched_movies:
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + 1
                else:
                    self.movies[movie] = 1
            for movie in user.liked_movies:
                pass

        sorted_movies = sorted(self.movies.items(), key=lambda x: (-x[1], x[0]))

        # find the lowest score of the x number of movies that are going to be recommended
        # to know how many ratings need to be looked up
        self.lowest_relevant_score = sorted_movies[self.limit_per_page - 1][1]

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
            rating = lb_movie.Movie(movie[1]).rating.split()[0]
            # protection for if the movie has no rating
            try:
                rating = float(rating)
            except:
                rating = float(0)
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

        self.working_on_recommendations = False
        self.recommendations_done = True
        await self.update_response()

    async def mark_attendance(self, value=None):
        working = True
        while working and value is not None:
            self.users[self.active_account_index].attendance_value = value

            if value == 0:
                self.present_users.append(self.users[self.active_account_index])
            elif value == 1:
                self.ignored_users.append(self.users[self.active_account_index])
            elif value == 2:
                self.absent_users.append(self.users[self.active_account_index])

            self.active_account_index += 1
            if self.active_account_index >= len(self.users):
                self.attendance_done = True
            if not self.apply_to_all or self.attendance_done:
                working = False

        if self.attendance_done:
            self.taking_attendance = False

            if len(self.present_users) < 1:
                self.embed_desc_gathering += f"\nCannot recommend anything since there are no present linked members"
                await self.update_response()
                return

            await self.collect_movies()

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
