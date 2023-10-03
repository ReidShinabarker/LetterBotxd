# recommend.py

import discord
from discord.ext import commands
import database
from letterboxdpy import user as lb_user
from letterboxdpy import movie as lb_movie


class Recommendation(discord.ui.View):
    def __init__(self, show_ratings):
        super().__init__()
        self.initiator: discord.Interaction = None
        self.show_ratings = show_ratings
        self.apply_to_all = False
        self.taking_attendance = False
        self.active_user = None
        self.embed_title = "**MOVIE RECOMMENDATION**"
        self.embed_desc = "Recommendation initiated..."
        self.lb_accounts = []
        self.discord_members = []
        self.movies = {}
        self.lowest_relevant_score = None
        self.limit_per_page = 10

    async def initiate(self, initiator: discord.Interaction):
        self.initiator = initiator
        await initiator.response.send_message(embed=await self.make_embed())
        await self.find_accounts()
        await self.collect_movies()
        await self.check_watched()
        if self.show_ratings:
            await self.check_ratings()
        await self.calculate_recommendation()

    async def update_response(self):
        await self.initiator.edit_original_response(embed=await self.make_embed(),
                                                    view=self if self.taking_attendance else None)

    async def make_embed(self):
        embed = discord.Embed(title=self.embed_title, description=self.embed_desc)
        return embed

    async def find_accounts(self):
        cursor = await database.get_cursor()
        cursor.execute(f"SELECT users.member, users.account FROM users, memberships WHERE "
                       f"memberships.member=users.member AND memberships.guild='{self.initiator.guild_id}'")

        self.embed_desc += f"\nFinding linked Letterboxd accounts..."
        await self.update_response()

        for item in cursor:
            self.lb_accounts.append(lb_user.User(str(item[1])))
            self.discord_members.append(self.initiator.client.get_user(int(item[0])))

        cursor.close()

    async def collect_movies(self):
        self.embed_desc += f"\nCollecting movies in watchlists..."
        await self.update_response()
        for user in self.lb_accounts:
            for movie in lb_user.user_films_on_watchlist(user):
                # increment the key of a movie by 2 for each watchlist it is in
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] + 2
                else:
                    self.movies[movie] = 2

    async def check_watched(self):
        self.embed_desc += f"\nChecking which movies have already been seen by people..."
        await self.update_response()
        for user in self.lb_accounts:
            for movie in lb_user.user_films_watched(user):
                # decrement the key of a movie by 1 for each person that has seen it
                if movie in self.movies:
                    self.movies[movie] = self.movies[movie] - 1

        # this is sorted twice so that it can be in reverse score sort and not reversed alphabetical
        sorted_movies = sorted(self.movies.items(), key=lambda x: (x[0]))
        sorted_movies = sorted(sorted_movies, key=lambda x: (x[1]), reverse=True)

        # find the lowest score of the x number of movies that are going to be recommended
        # to know how many ratings need to be looked up
        self.lowest_relevant_score = sorted_movies[self.limit_per_page-1][1]

        # convert back to dict to be easier to work with
        self.movies = dict(sorted_movies)

    async def check_ratings(self):
        self.embed_desc += f"\nObjectively calculating how good each movie is..."
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

    async def calculate_recommendation(self):
        self.embed_desc += f"\nCalculating recommendations..."
        await self.update_response()

        full_response = ''
        poster_link = ''
        i = 0
        score_column = ''
        title_column = ''
        rating_column = ''
        for movie, score in self.movies.items():
            if i >= self.limit_per_page:
                break
            if poster_link == '':
                poster_link = lb_movie.movie_poster(movie[1])

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

        final_embed = discord.Embed(title=self.embed_title, description=full_response)
        final_embed.set_image(url=poster_link)
        final_embed.add_field(name="SCORE", value=score_column)
        final_embed.add_field(name="TITLE", value=title_column)
        if self.show_ratings:
            final_embed.add_field(name="RATING", value=rating_column)
        await self.initiator.edit_original_response(embed=final_embed)

    @discord.ui.button(label="PRESENT", style=discord.ButtonStyle.green)
    async def present_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="IGNORE", style=discord.ButtonStyle.grey)
    async def ignore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="ABSENT", style=discord.ButtonStyle.red)
    async def absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="🟩 APPLY TO REMAINING")
    async def all_button_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.apply_to_all = not self.apply_to_all
        button.label = ("✅" if self.apply_to_all else "🟩") + " APPLY TO REMAINING"
        await self.update_response()
        await interaction.response.defer()
