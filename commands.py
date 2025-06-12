import traceback
import io
from pathlib import Path
import os
import sys
from typing import TYPE_CHECKING, Literal
import asyncio

import discord
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext import commands
from PIL import Image

import config

if TYPE_CHECKING:
    from main import Context, Bot
else:
    Context = None
    Bot = None

async def error(interaction: Interaction, *args, **kwargs):
    return await respond(interaction, *args, ephemeral=True, **kwargs)

async def respond(interaction: Interaction, content: str | None = None, *, edit: bool = False, **kwargs):
    if interaction.response.is_done():
        if edit:
            if "ephemeral" in kwargs: del kwargs["ephemeral"]
            return await (await interaction.original_response()).edit(**kwargs, content=content)
        return await interaction.followup.send(content, **kwargs)
    return await interaction.response.send_message(content, **kwargs)

class CommandCog(commands.Cog, name = "Commands"):
    def __init__(self, bot: Bot):
        self.bot = bot
        print("Loading commands...")

        @bot.tree.command()
        async def element(intr: Interaction, query: str, genderswapped: bool = False):
            """
            Gets an element by their name, symbol, or atomic number.
            """
            await intr.response.defer(thinking=True)
            query = query.strip()
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
                return await error(intr, f"No element found with name, symbol, or atomic number `{query}`!")   
            
            genderswapped &= not element.oc

            icon = self.bot.get_element_icon(element, genderswapped)
            width, height = icon.size
            icon = icon.resize((width * config.icon_scale, height * config.icon_scale), Image.Resampling.NEAREST)

            emb = discord.Embed (
                color=element.embed_color,
                title=element.name
            )
            emb.add_field(name="Symbol", value=element.symbol)
            if element.atomic_number is not None:
                emb.add_field(name="Atomic Number", value=element.atomic_number)
            pronouns = element.pronouns
            if genderswapped and "/" in pronouns:
                parts = pronouns.split("/")
                table = {"he": "she", "him": "her", "she": "he", "her": "him", "hse": "eh", "ehr": "ihm", "him...?": "her...?"}
                pronouns = "/".join(table.get(part, part) for part in parts)
            emb.add_field(name="Pronouns", value=pronouns)
            emb.add_field(name="Author", value=element.author, inline = False)
            if element.atomic_number is not None:
                emb.add_field(name="Wiki Page", value=f"[[link]](<https://elementcattos.miraheze.org/wiki/{element.name}>)", inline = True)
            buf = io.BytesIO()
            icon.save(buf, format = "PNG")
            buf.seek(0)
            raw_name = "".join(c if c.isalnum() else "_" for c in element.name).lower()
            path = f"{raw_name}.png"
            emb.set_image(url=f"attachment://{path}")
            file = discord.File(buf, path)
            return await respond(intr, embed=emb, files=[file])
        
        @element.autocomplete("query")
        async def complete_query(interaction: Interaction, query: str):
            query = query.strip().lower()
            if len(query) > 0 and query.isdecimal() and query.isascii():
                return []
            choices = set()
            for el in self.bot.elements_by_name.values():
                if el.name.lower().startswith(query):
                    choices.add(el.name)
            return [Choice(name=choice, value=choice) for choice in sorted(choices, key = lambda str: str.lower())][:25]

        @bot.tree.command()
        async def table(intr: Interaction, query: str):
            """Gets an entire table."""
            await intr.response.defer(thinking=True)
            query = query.strip().lower()
            try:
                table = self.bot.tables[query]
            except KeyError:
                query = query.replace("`", "").replace("\n", "")[:32]
                return await error(intr, f"No table found with name `{query}`!")
            emb = discord.Embed(color=0xFFFFFF)
            buf = io.BytesIO()
            table.save(buf, format = "PNG")
            buf.seek(0)
            path = f"{query}.png"
            emb.set_image(url=f"attachment://{path}")
            file = discord.File(buf, path)
            return await respond(intr, embed=emb, files=[file])

        @table.autocomplete("query")
        async def complete_query(interaction: Interaction, query: str):
            query = query.strip().lower()
            choices = set()
            for table in self.bot.tables.values():
                if table.lower().startswith(query):
                    choices.add(el.name)
            return [Choice(name=choice, value=choice) for choice in sorted(choices, key = lambda str: str.lower())][:25]

        @bot.tree.command()
        async def sync(intr: Interaction):
            """Syncs the table to the bot. Owner-only."""
            await intr.response.defer(thinking=True)
            assert await self.bot.is_owner(intr.user), "This command can only be run by the bot's owners!"
            self.bot.sync_image()
            self.bot.load_elements()
            return await respond(intr, "Synced image!", ephemeral=True)

        @bot.tree.command()
        async def sync_tree(interaction: Interaction, testing: bool = True):
            await interaction.response.defer(thinking=True)
            TESTING_GUILD = discord.Object(586337032876589075)
            assert await self.bot.is_owner(interaction.user), "This command can only be run by the bot's owners!"
            await self.bot.tree.sync(guild=TESTING_GUILD if testing else None)
            await respond(interaction, "Synced!", ephemeral=True)

    def cog_load(self):
        tree = self.bot.tree
        self._old_tree_error = tree.on_error
        tree.on_error = self.on_app_command_error

    def cog_unload(self):
        tree = self.bot.tree
        tree.on_error = self._old_tree_error

    async def on_app_command_error(
        self,
        interaction: Interaction,
        err
    ):
        try:
            if isinstance(err, app_commands.CommandInvokeError) or isinstance(err, commands.ExtensionFailed):
                err = err.original
            if isinstance(err, app_commands.CheckFailure):
                return await respond(interaction, "This command can only be run by the owners of the bot!", ephemeral=True)
            if isinstance(err, AssertionError):
                return await respond(interaction, f"{err.args[0]}", ephemeral=True)

            tb = "\n".join(traceback.format_exception(err, chain=False, limit=-5))
            await respond(interaction, f"Unhandled exception occurred! {err}\n```py\n{tb[-1900:]}\n```", ephemeral=True)
        except discord.errors.InteractionResponded:
            # Probably already handled earlier
            traceback.print_exception(err)

async def setup(bot: Bot):
    await bot.add_cog(CommandCog(bot))
