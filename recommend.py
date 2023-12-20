# recommend.py
import math

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


class ScoringRules:
    def __init__(self):
        self.watchlist_present = 5
        self.watchlist_absent = -7
        self.watched_present = -2
        self.watched_absent = 1
        self.liked_present = 1
        self.liked_absent = 1

    def change_rules(self, present_scores: tuple, absent_scores: tuple):
        self.watchlist_present = present_scores[0]
        self.watched_present = present_scores[1]
        self.liked_present = present_scores[2]

        self.watched_absent = absent_scores[0]
        self.watched_absent = absent_scores[1]
        self.liked_absent = absent_scores[2]

    def get_rules(self):
        score_tuple = (self.watchlist_present, self.watched_present, self.liked_present,
                       self.watchlist_absent, self.watched_absent, self.liked_absent)
        return score_tuple


class Recommendation:
    def __init__(self, channel_for_attendance: discord.VoiceChannel):
        # slash command Interaction object
        self.initiator: discord.Interaction = None

        # progression states
        self.taking_attendance = False
        self.attendance_done = False
        self.recommendations_done = False

        # views
        self.view_attendance = None
        self.view_final = None

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
        self.limit_per_page = 10
        self.scoring_rules = ScoringRules()

        # variables
        self.active_account_index = 0
        self.current_page = 0
        self.total_pages = 0
        self.loading_recalculation = False

    async def initiate(self, initiator: discord.Interaction):
        self.initiator = initiator

        # views are created down here so that they can get reference to this initiator during their __init__
        self.view_attendance = AttendanceView(self)
        self.view_final = FinalView(self)

        await initiator.response.send_message(embeds=await self.make_embeds())
        await self.find_accounts()

    async def update_response(self):
        await self.initiator.edit_original_response(embeds=await self.make_embeds(),
                                                    view=self.get_view())

    async def make_embeds(self):
        embeds = []
        if self.recommendations_done:
            recommend_embed = discord.Embed(title="**MOVIE RECOMMENDATIONS**")
            recommend_embed.set_image(url=self.poster_link)
            footer = f"page {self.current_page+1}/{self.total_pages}"
            if self.loading_recalculation:
                footer = f"loading {footer}... please be patient"
            recommend_embed.set_footer(text=footer)
            for field in self.embed_fields_recommendation:
                recommend_embed.add_field(name=field[0], value=field[1])
            embeds.append(recommend_embed)

            scoring_embed = discord.Embed(title="**SCORING RULES**")
            rules = self.scoring_rules.get_rules()
            scoring_embed.add_field(name="_ _", value="**Movie on watchlist: **\n"
                                                      "**Already watched movie: **\n"
                                                      "**Liked movie: **")
            scoring_embed.add_field(name="**PRESENT**", value=f"{rules[0]}\n"
                                                              f"{rules[1]}\n"
                                                              f"{rules[2]}")
            scoring_embed.add_field(name="**ABSENT**", value=f"{rules[3]}\n"
                                                             f"{rules[4]}\n"
                                                             f"{rules[5]}")
            embeds.append(scoring_embed)

        else:
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
            users_string = ""
            for user in self.present_users:
                users_string += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**PRESENT**", value=users_string)

            users_string = ""
            for user in self.ignored_users:
                users_string += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**IGNORED**", value=users_string)

            users_string = ""
            for user in self.absent_users:
                users_string += f"{await user.display_user()}\n"
            attendance_embed.add_field(name="**ABSENT**", value=users_string)

            embeds.append(attendance_embed)

        return embeds

    def get_view(self):
        if self.taking_attendance:
            return self.view_attendance
        if self.recommendations_done:
            return self.view_final
        return None

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
        self.embed_desc_gathering += f"\nCollecting movies in watchlists..."
        await self.update_response()
        for user in self.users:
            user.watchlist = lb_user.user_films_on_watchlist(user.account)

        self.embed_desc_gathering += f"\nCollecting movies that have already been seen..."
        await self.update_response()
        for user in self.users:
            user.watched_movies = lb_user.user_films_watched(user.account)

        self.embed_desc_gathering += f"\nCollecting movies that have been liked..."
        await self.update_response()
        for user in self.users:
            user.liked_movies = lb_user.user_films_liked(user.account)

        await self.apply_scoring()

    async def apply_scoring(self):
        self.embed_desc_gathering += f"\nApplying the scoring rules to the movies eligible for recommendation..."
        await self.update_response()

        def add_score(value: int, film, add_movie=False):
            if film in self.movies:
                self.movies[film] = (self.movies[film][0] + value, 0.0, 0)
            elif add_movie:
                self.movies[film] = (value, 0.0, 0)

        score_rules = ScoringRules.get_rules(self.scoring_rules)

        # populate list with watchlisted movies
        for user in self.present_users:
            for movie in user.watchlist:
                add_score(score_rules[0], movie, True)

        # apply scoring for present users
        for user in self.present_users:
            for movie in user.watched_movies:
                add_score(score_rules[1], movie)
            for movie in user.liked_movies:
                add_score(score_rules[2], movie)

        # apply scoring for absent users
        for user in self.absent_users:
            for movie in user.watchlist:
                add_score(score_rules[3], movie)
            for movie in user.watched_movies:
                add_score(score_rules[4], movie)
            for movie in user.liked_movies:
                add_score(score_rules[5], movie)

        await self.calculate_recommendation()

    async def calculate_recommendation(self):
        self.embed_desc_gathering += f"\nCalculating recommendations..."
        await self.update_response()

        async def find_data_for_score(my_score):
            for my_movie in list(self.movies):
                if self.movies[my_movie][0] == my_score:
                    await find_movie_data(my_movie)

        async def find_movie_data(my_movie):
            movie_data = lb_movie.Movie(my_movie[1])
            my_rating = movie_data.rating.split()[0]
            my_runtime = movie_data.runtime

            # protection for if the movie has no rating
            try:
                my_rating = float(my_rating)
            except:
                my_rating = float(0)

            # protection for if the movie has no runtime
            try:
                my_runtime = int(my_runtime)
            except:
                my_runtime = None

            if my_rating != 0.0:
                self.movies[my_movie] = (self.movies[my_movie][0], my_rating, my_runtime)
            else:
                del self.movies[my_movie]

        # loop this until we get a page that is fully populated with movies with ratings
        trying = True
        while trying:

            self.poster_link = ''
            start = self.current_page * self.limit_per_page
            end = min(start + self.limit_per_page, len(self.movies) - 1)
            i = 0
            score_column = ''
            title_column = ''
            rating_column = ''

            self.movies = dict(sorted(self.movies.items(), key=lambda x: (x[1][0], x[1][1]), reverse=True))

            for movie, data in self.movies.items():
                if i < start:
                    i += 1
                    continue
                if i >= end:
                    trying = False
                    break
                if data[1] == 0.0:
                    await find_data_for_score(data[0])
                    break

                if self.poster_link == '':
                    self.poster_link = lb_movie.movie_poster(movie[1])

                score = f"{data[0]}\n"
                name = f"[{movie[0]}](https://www.letterboxd.com/film/{movie[1]}/)\n"
                rating = f"{float(data[1]):.2f}"
                runtime = f"{int(data[2]) // 60}:{(int(data[2]) % 60):02d}"

                # field bodies can't go over 1024 characters
                # if (len(score) + len(score_column) >= 1024 or
                #         len(name) + len(title_column) >= 1024 or
                #         len(rating) + len(rating_column) >= 1024):
                #     break

                score_column += score
                title_column += name
                rating_column += f"{rating}  -  {runtime}\n"
                i += 1

        self.embed_fields_recommendation = [("SCORE", score_column),
                                            ("TITLE", title_column),
                                            ("RATING & RUNTIME", rating_column)]

        self.total_pages = int(math.ceil(len(self.movies) / self.limit_per_page))

        self.recommendations_done = True
        self.loading_recalculation = False
        await self.update_response()

    async def mark_attendance(self, value=None, recursive=False):
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
            if not recursive or self.attendance_done:
                working = False

        if self.attendance_done:
            self.taking_attendance = False

            if len(self.present_users) < 1:
                self.embed_desc_gathering += f"\nCannot recommend anything since there are no present linked members"
                await self.update_response()
                return

            await self.collect_movies()

        await self.update_response()


# Views are defined down here so that the required Recommendation is already defined
class AttendanceView(discord.ui.View):
    def __init__(self, parent: Recommendation):
        super().__init__()
        self.parent = parent
        self.initiator = parent.initiator

        self.apply_to_all = False

    @discord.ui.button(label="PRESENT", style=discord.ButtonStyle.green)
    async def present_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.parent.mark_attendance(value=0, recursive=self.apply_to_all)

    @discord.ui.button(label="IGNORE", style=discord.ButtonStyle.grey)
    async def ignore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.parent.mark_attendance(value=1, recursive=self.apply_to_all)

    @discord.ui.button(label="ABSENT", style=discord.ButtonStyle.red)
    async def absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        await self.parent.mark_attendance(value=2, recursive=self.apply_to_all)

    @discord.ui.button(label="🟩 APPLY TO REMAINING", style=discord.ButtonStyle.blurple)
    async def all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator.user:
            await interaction.response.defer()
            return
        self.apply_to_all = not self.apply_to_all
        button.label = ("✅" if self.apply_to_all else "🟩") + " APPLY TO REMAINING"
        await self.parent.update_response()
        await interaction.response.defer()


class FinalView(discord.ui.View):
    def __init__(self, parent: Recommendation):
        super().__init__()
        self.parent = parent
        self.initiator = parent.initiator

    @discord.ui.button(label="|<", style=discord.ButtonStyle.green, disabled=True)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        self.parent.current_page = 0
        await self.update_buttons()

    @discord.ui.button(label="<", style=discord.ButtonStyle.green, disabled=True)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        if self.parent.current_page > 0:
            self.parent.current_page -= 1
        await self.update_buttons()

    @discord.ui.button(label=">", style=discord.ButtonStyle.green)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        if self.parent.current_page < self.parent.total_pages - 1:
            self.parent.current_page += 1
        await self.update_buttons()

    @discord.ui.button(label=">|", style=discord.ButtonStyle.green)
    async def last_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user != self.initiator.user:
            return
        self.parent.current_page = self.parent.total_pages - 1
        await self.update_buttons()

    async def update_buttons(self):
        self.first_button.disabled = False
        self.previous_button.disabled = False
        self.last_button.disabled = False
        self.next_button.disabled = False

        if self.parent.current_page == 0:
            self.first_button.disabled = True
            self.previous_button.disabled = True

        if self.parent.current_page == self.parent.total_pages - 1:
            self.last_button.disabled = True
            self.next_button.disabled = True

        self.parent.loading_recalculation = True
        await self.parent.calculate_recommendation()
