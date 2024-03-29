from nextcord.ext import commands
import nextcord
from voice_state import VoiceState, VoiceError
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from ytdlsource import YTDLError, YTDLSource
from song import Song
import math
from dotenv import load_dotenv


log = logging.getLogger(__name__)

load_dotenv("env/.env")
spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID")
spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

# Spotipy
sp = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=spotify_client_id, client_secret=spotify_client_secret
    )
)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    async def get_spotify_songs_from_playlist(self, playlist_url: str):
        """Get songs from a Spotify playlist

        Args:
            playlist_url (str)

        Returns:
            list: list with str containing song name and artist
        """
        results = sp.playlist_tracks(playlist_url)
        tracks = results["items"]
        output = []
        count = 0

        while results["next"]:
            results = sp.next(results)
            tracks.extend(results["items"])
        for track in tracks:
            if count == 50:
                return output
            output.append(
                track["track"]["artists"][0]["name"] + " " + track["track"]["name"]
            )
        return output

    async def get_spotify_songs_from_album(self, album_url: str):
        """Get songs from a Spotify album

        Args:
            album_url (str)

        Returns:
            list: list with str containing song name and artist
        """
        results = sp.album_tracks(album_url)
        tracks = results["items"]
        output = []
        while results["next"]:
            results = sp.next(results)
            tracks.extend(results["items"])

        for track in tracks:
            output.append(track["artists"][0]["name"] + " " + track["name"])
        return output

    async def get_song(self, song_url: str):
        results = sp.track(song_url)
        output = results["artists"][0]["name"] + " " + results["name"]
        return output

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.context.Context, command_exception: commands.CommandError
    ):

        if isinstance(command_exception, commands.MissingRequiredArgument):
            log.error("Missing required argument: {}".format(str(command_exception)))
            await ctx.send("Missing required argument")

        if isinstance(command_exception, commands.BadArgument):
            log.error("Bad argument: {}".format(str(command_exception)))

            await ctx.send("Bad argument")

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage(
                "This command can't be used in DM channels."
            )

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        log.error("An error occurred: {}".format(str(error)))

    @commands.command(name="join", invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name="summon")
    @commands.has_permissions(manage_guild=True)
    async def _summon(
        self, ctx: commands.Context, *, channel: nextcord.VoiceChannel = None
    ):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError(
                "You are neither connected to a voice channel nor specified a channel to join."
            )

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name="leave", aliases=["disconnect"])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send("Not connected to any voice channel.")

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name="volume")
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send("Nothing being played at the moment.")

        if 0 > volume > 100:
            return await ctx.send("Volume must be between 0 and 100")

        ctx.voice_state.volume = volume / 100
        await ctx.send("Volume of the player set to {}%".format(volume))

    @commands.command(name="now", aliases=["current", "playing"])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name="pause")
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction("⏯")

    @commands.command(name="resume")
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction("⏯")

    @commands.command(name="stop")
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction("⏹")

    @commands.command(name="skip", aliases=["next"])
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("Not playing any music right now...")

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction("⏭")
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction("⏭")
                ctx.voice_state.skip()
            else:
                await ctx.send(
                    "Skip vote added, currently at **{}/3**".format(total_votes)
                )

        else:
            await ctx.send("You have already voted to skip this song.")

    @commands.command(name="queue")
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ""
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += "`{0}.` [**{1.source.title}**]({1.source.url})\n".format(
                i + 1, song
            )

        embed = nextcord.Embed(
            description="**{} tracks:**\n\n{}".format(len(ctx.voice_state.songs), queue)
        ).set_footer(text="Viewing page {}/{}".format(page, pages))
        await ctx.send(embed=embed)

    @commands.command(name="shuffle")
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction("✅")

    @commands.command(name="remove")
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("Empty queue.")

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction("✅")

    @commands.command(name="loop")
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("Nothing being played at the moment.")

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction("✅")

    async def process_spotify_query(self, ctx: commands.Context, search: str):
        """Adds songs from a spotify query to the queue.

        Args:
           ctx (commands.Context): The context of the command
           search (str): spotify link
        """
        if "track" in search:
            track = await self.get_song(search)
            try:
                source = await YTDLSource.create_source(ctx, track, loop=self.bot.loop)

            except YTDLError as e:
                await ctx.send(
                    "An error occurred while processing this request: {}".format(str(e))
                )

            else:
                song = Song(source)
                await ctx.voice_state.songs.put(song)
                await ctx.send("Enqueued {}".format(str(source)))

        else:

            if "album" in search:
                tracks = await self.get_spotify_songs_from_album(search)

            if "playlist" in search:
                tracks = await self.get_spotify_songs_from_playlist(search)

            count = 1
            message = await ctx.send("Adding songs")

            for track in tracks:
                try:
                    source = await YTDLSource.create_source(
                        ctx, track, loop=self.bot.loop
                    )

                except YTDLError as e:
                    await ctx.send(
                        "An error occurred while processing this request: {}".format(
                            str(e)
                        )
                    )
                    await message.delete()

                else:
                    song = Song(source)
                    await ctx.voice_state.songs.put(song)
                    string = "Added song {}/".format(count)
                    string = string + str(len(tracks))
                    await message.edit(content=string)

                    count += 1
            await ctx.send("Enqueued all songs")

    @commands.command(name="p", aliases=["play", "P"])
    async def _play(self, ctx: commands.context.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """
        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():

            if "spotify" in search:

                await self.process_spotify_query(ctx, search)

            else:
                try:

                    source = await YTDLSource.create_source(
                        ctx, search, loop=self.bot.loop
                    )
                except YTDLError as e:
                    await ctx.send(
                        "An error occurred while processing this request: {}".format(
                            str(e)
                        )
                    )
                else:
                    song = Song(source)

                    await ctx.voice_state.songs.put(song)
                    await ctx.send("Enqueued {}".format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError("You are not connected to any voice channel.")

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError("Bot is already in a voice channel.")
