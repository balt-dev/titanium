import traceback
import io
from pathlib import Path
import os
import sys
from typing import TYPE_CHECKING
import asyncio

import discord
from discord.ext import commands
from PIL import Image

import config

if TYPE_CHECKING:
    from main import Context, Bot
else:
    Context = None
    Bot = None

class CommandCog(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        print("Loading commands...")

    @commands.command(aliases=["e", "el", "elem", "t", "tab", "table"])
    async def element(self, ctx: Context, *, query: str | None = None):
        """
        Gets an element by their name, symbol, or atomic number.
        Specifying no element will show the entire table.
        """
        async with ctx.typing():
            if self.bot.table is None:
                self.bot.sync_image()
            if query is None:
                emb = discord.Embed(title="The Purriodic Table")
                buf = io.BytesIO()
                self.bot.table.save(buf, format="PNG")
                buf.seek(0)
                file = discord.File(buf, "table.png")
                emb.set_image(url="attachment://table.png")
                return await ctx.reply(embed=emb, files=[file])
            if query == "nonperiodic":
                emb = discord.Embed(title="The Non-Purriodic Table")
                file = discord.File("elements/nonperiodics.png", "table.png")
                emb.set_image(url="attachment://table.png")
                return await ctx.reply(embed=emb, files=[file])
            # Parse the element's name
            query = query.lower()
            if query in self.bot.elements_by_name:
                element = self.bot.elements_by_name[query]
            elif query in self.bot.elements_by_symbol:
                element = self.bot.elements_by_symbol[query]
            elif (
                query.isascii() and
                query.isdecimal() and
                len(query) > 0 and
                (atomic_number := int(query)) in self.bot.elements_by_atomic_number
            ):
                element = self.bot.elements_by_atomic_number[atomic_number]
            else:
                query = query.replace("`", "").replace("\n", "")[:32]
                return await ctx.error(f"No element found with name, symbol, or atomic number `{query}`!")
            emb = discord.Embed (
                color=element.embed_color,
                title=element.name
            )
            emb.add_field(name="Symbol", value=element.symbol)
            if element.atomic_number >= 0:
                emb.add_field(name="Atomic Number", value=element.atomic_number)
            emb.add_field(name="Pronouns", value=element.pronouns)
            emb.add_field(name="Author", value=element.author, inline = False)
            path = hex(hash(element.name)) + ".gif"
            emb.set_image(url="attachment://" + path)
            icon = tuple(icon[0].resize(((config.element_size[0] + 2) * config.icon_scale, (config.element_size[1] + 2) * config.icon_scale), Image.Resampling.NEAREST) for icon in element.icon)
            buf = io.BytesIO()
            icon[0].save(
                buf,
                format = "GIF",
                save_all = True,
                append_images = icon[1:],
                duration = [i[1] for i in element.icon]
            )
            buf.seek(0)
            file = discord.File(buf, path)
            return await ctx.reply(embed=emb, files=[file])

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx: Context):
        """Reloads the bot's commands. Owner-only."""
        async with ctx.typing():
            await self.bot.reload_extension("commands")
            return await ctx.reply("Reloaded!")

    @commands.group()
    @commands.is_owner()
    async def toml(self, ctx: Context):
        """Sends or recieves elements.toml. Owner-only."""
        ...
    
    @toml.command()
    @commands.is_owner()
    async def get(self, ctx: Context):
        """Sends elements.toml. Owner only."""
        return await ctx.reply(files = [discord.File("elements.toml")])
    
    @commands.is_owner()
    async def set(self, ctx: Context, attachment: discord.Attachment):
        """Sends elements.toml. Owner only."""
        await attachment.save("elements.toml")
        return await ctx.reply("Saved! Run `.sync`.")

    @commands.command()
    @commands.is_owner()
    async def sync(self, ctx: Context):
        """Syncs the table to the bot. Owner-only."""
        async with ctx.typing():
            self.bot.sync_image()
            self.bot.load_elements()
            return await ctx.reply("Synced image!")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: Context, error: Exception):
        """Handles an error."""
        try:
            if hasattr(ctx.command, 'on_error'):
                return

            ignored = (
                commands.CommandNotFound,
                commands.NotOwner,
                commands.CheckFailure
            )
            if isinstance(error, ignored):
                return

            # Allows us to check for original exceptions raised and sent to CommandInvokeError.
            # If nothing is found. We keep the exception passed to
            # on_command_error.
            error = getattr(error, 'original', error)

            emb = discord.Embed(title="Command Error", color=0xffff00)
            emb.description = str(error)

            # Adds embed fields
            # Bot
            if self.bot.user:  # tautology but fits the scheme
                message_id = self.bot.user.id
                name = self.bot.user.display_name
            # Message
            if ctx.message:
                message_id = ctx.message.id
                content = ctx.message.content
                if len(content) > 1024:
                    content = content[1000] + "`...`"
                formatted = f"ID: {message_id}\nContent: `{content}`"
                emb.add_field(name="Message", value=formatted)
            # Channel
            if isinstance(ctx.channel, discord.TextChannel):
                message_id = ctx.channel.id
                name = ctx.channel.name
                nsfw = "[NSFW Channel] " if ctx.channel.is_nsfw() else ""
                news = "[News Channel] " if ctx.channel.is_news() else ""
                formatted = f"message_id: {message_id}\nName: {name}\n{nsfw}{news}"
                emb.add_field(name="Channel", value=formatted)
            # Guild (if in a guild)
            if ctx.guild is not None:
                ID = ctx.guild.id
                name = ctx.guild.name
                member_count = ctx.guild.member_count
                formatted = f"ID: {ID}\nName: {name}\nMember count: {member_count}"
                emb.add_field(name="Guild", value=formatted)
            # Author (DM information if any)
            if ctx.author:
                ID = ctx.author.id
                name = ctx.author.name
                discriminator = ctx.author.discriminator
                nick = f"({ctx.author.nick})" if ctx.guild else ""
                DM = "Message Author" if ctx.guild else "Direct Message"
                formatted = f"ID: {ID}\nName: {name}#{discriminator} ({nick})"
                emb.add_field(name=DM, value=formatted)
            # Message link
            if all([ctx.guild is not None, ctx.channel, ctx.message]):
                guild_ID = ctx.guild.id
                channel_ID = ctx.channel.id
                message_ID = ctx.message.id
                formatted = f"[Jump to message](https://discordapp.com/channels/{guild_ID}/{channel_ID}/{message_ID})"
                emb.add_field(name="Jump", value=formatted)
            if isinstance(error, commands.CommandOnCooldown):
                if ctx.author.id == self.bot.owner_id:
                    return await ctx.reinvoke()
                else:
                    return await ctx.error(str(error))

            elif isinstance(error, commands.DisabledCommand):
                await ctx.error(f'{ctx.command} has been disabled.')

            elif isinstance(error, commands.ExpectedClosingQuoteError):
                return await ctx.error(f"Expected closing quotation mark `{error.close_quote}`.")

            elif isinstance(error, commands.InvalidEndOfQuotedStringError):
                return await ctx.error(f"Expected a space after a quoted string, got `{error.char}` instead.")

            elif isinstance(error, commands.UnexpectedQuoteError):
                return await ctx.error(f"Got unexpected quotation mark `{error.quote}` inside a string.")

            elif \
                isinstance(error, commands.ConversionError) \
                or isinstance(error, commands.BadArgument) \
                or isinstance(error, commands.ArgumentParsingError) \
                or isinstance(error, commands.MissingRequiredArgument):
                return await ctx.error("Command arguments were invalid! Check the entry in `.help` for the correct format.")

            elif isinstance(error, AssertionError) or isinstance(error, NotImplementedError):
                return await ctx.error(error.args[0])

            elif isinstance(error, discord.errors.HTTPException):
                return await ctx.error(f"Ran into an HTTP error of code {error.status}.")
            else:
                raise error
        except Exception as error:
            if os.name == "nt":
                trace = '\n'.join(
                    traceback.format_tb(
                        error.__traceback__)).replace(
                    os.getcwd(),
                    os.path.curdir).replace(
                    os.environ["USERPROFILE"],
                    "")
            else:
                trace = '\n'.join(
                    traceback.format_tb(
                        error.__traceback__)).replace(
                    os.getcwd(),
                    os.path.curdir)
            if len(trace) > 1000:
                trace = trace[:500] + "\n\n...\n\n" + trace[-500:] 
            title = f'**Unhandled exception!**'
            err_desc = f"An unhandled error occurred within the code. Contact the bot owner ASAP!\n**{type(error).__name__}**: {error}"
            err_desc = f"{err_desc}\n```\n{trace}\n```"
            if len(err_desc) > 500:
                err_desc = err_desc[:250] + "..." + err_desc[-250:]
            emb = discord.Embed(
                title=title,
                description=err_desc,
                color=15029051
            )
            await ctx.error(msg='', embed=emb)
            print(
                f'Ignoring exception in command {ctx.command}:',
                file=sys.stderr)
            traceback.print_exception(
                type(error),
                error,
                error.__traceback__,
                file=sys.stderr)

async def setup(bot: Bot):
    await bot.add_cog(CommandCog(bot))
    print("Loaded commands!")
