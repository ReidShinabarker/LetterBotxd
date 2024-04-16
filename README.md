A Discord bot to help server members decide on a movie to watch based on their Letterboxd accounts.

After pairing members' letterboxd accounts to their Discord accounts through bot commands, the /Recommendation command will begin a process to help the users pick the optimal movie for them to watch as a group.
Attendance is taken at the start of the Recommendation to determine who will be present or absent for the movie, or if they should be ignored for the process.
The list of potential recommendations is the union of all present members' watchlists.
The priority of the recommendation is scored based on what users want to or have already seen a movie, and by whether or not a user is present or absent.

The output of the Recommendation is given in a Discord embed message, showing 10 results per page with the movie's title, year, runtime, and average Letterboxd rating.
