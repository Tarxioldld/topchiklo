# Credits and original author: https://github.com/fourjr/modmail-plugins/blob/master/claim/claim.py
# Slightly modified for Minion_Kadin#2022 (discord)
# Please use the original plugin as this one may cause your bot to nuke the world

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.utils import match_user_id


class ClaimThread(commands.Cog):
    """Allows supporters to claim thread by sending claim in the thread channel"""
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        check_reply.fail_msg = 'This thread has been claimed by another user.'
        self.bot.get_command('reply').add_check(check_reply)
        self.bot.get_command('areply').add_check(check_reply)
        self.bot.get_command('fareply').add_check(check_reply)
        self.bot.get_command('freply').add_check(check_reply)
        
        # Notification channel ID
        self.notification_channel_id = 1247301906691526827  # Set your channel ID here

    async def check_claimer(self, ctx, claimer_id):
        config = await self.db.find_one({'_id': 'config'})
        if config and 'limit' in config:
            if config['limit'] == 0:
                return True
        else:
            raise commands.BadArgument(f"Set Limit first. `{ctx.prefix}claim limit`")

        cursor = self.db.find({'guild': str(self.bot.modmail_guild.id)})
        count = 0
        async for x in cursor:
            if 'claimers' in x and str(claimer_id) in x['claimers']:
                count += 1

        return count < config['limit']

    async def check_before_update(self, channel):
        if channel.guild != self.bot.modmail_guild or await self.bot.api.get_log(channel.id) is None:
            return False

        return True

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if await self.check_before_update(channel):
            await self.db.delete_one({'thread_id': str(channel.id), 'guild': str(self.bot.modmail_guild.id)})

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.group(name='claim', invoke_without_command=True)
    async def claim_(self, ctx, subscribe: bool = True):
        """Claim a thread"""
        if not ctx.invoked_subcommand:
            if not await self.check_claimer(ctx, ctx.author.id):
                return await ctx.reply(f"Limit reached, can't claim the thread.")

            thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(self.bot.modmail_guild.id)})
            recipient_id = match_user_id(ctx.thread.channel.topic)
            recipient = self.bot.get_user(recipient_id) or await self.bot.fetch_user(recipient_id)

            embed = discord.Embed(
                color=self.bot.main_color,
                title="Ticket Claimed",
                description="Please wait as the assigned support agent reviews your case, you will receive a response shortly.",
                timestamp=ctx.message.created_at,
            )
            embed.set_footer(
                text=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url)

            description = ""
            if subscribe:
                if str(ctx.thread.id) not in self.bot.config["subscriptions"]:
                    self.bot.config["subscriptions"][str(ctx.thread.id)] = []

                mentions = self.bot.config["subscriptions"][str(ctx.thread.id)]

                if ctx.author.mention in mentions:
                    mentions.remove(ctx.author.mention)
                    description += f"{ctx.author.mention} will __not__ be notified of any message now.\n"
                else:
                    mentions.append(ctx.author.mention)
                    description += f"{ctx.author.mention} will now be notified of all messages received.\n"
                await self.bot.config.update()

            if thread is None:
                await self.db.insert_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(self.bot.modmail_guild.id), 'claimers': [str(ctx.author.id)]})
                async with ctx.typing():
                    await recipient.send(embed=embed)
                description += "Please respond to the case asap."
                embed.description = description
                await ctx.reply(embed=embed)
            elif thread and len(thread['claimers']) == 0:
                await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(self.bot.modmail_guild.id)}, {'$addToSet': {'claimers': str(ctx.author.id)}})
                async with ctx.typing():
                    await recipient.send(embed=embed)
                description += "Please respond to the case asap."
                embed.description = description
                await ctx.reply(embed=embed)
            else:
                description += "Thread is already claimed"
                embed.description = description
                await ctx.reply(embed=embed)

            # Notification in the specified channel
            if self.notification_channel_id:
                notification_channel = self.bot.get_channel(self.notification_channel_id)
                if notification_channel:
                    await notification_channel.send(
                        f"{ctx.author.mention} ({ctx.author.name}#{ctx.author.discriminator}, {ctx.author.top_role}) "
                        f"has claimed the ticket `{ctx.thread.channel.name}`."
                    )

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @commands.command()
    async def claims(self, ctx):
        """Check which channels you have claimed"""
        cursor = self.db.find({'guild': str(self.bot.modmail_guild.id)})
        channels = []
        async for x in cursor:
            if 'claimers' in x and str(ctx.author.id) in x['claimers']:
                try:
                    channel = ctx.guild.get_channel(int(x['thread_id'])) or await self.bot.fetch_channel(int(x['thread_id']))
                except discord.NotFound:
                    channel = None
                    await self.db.delete_one({'thread_id': x['thread_id'], 'guild': x['guild']})

                if channel and channel not in channels:
                    channels.append(channel)

        embed = discord.Embed(title='Your claimed tickets:', color=self.bot.main_color)
        embed.description = ', '.join(ch.mention for ch in channels)
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @claim_.command()
    async def cleanup(self, ctx):
        """Cleans up the database for deleted tickets"""
        cursor = self.db.find({'guild': str(self.bot.modmail_guild.id)})
        count = 0
        async for x in cursor:
            try:
                channel = ctx.guild.get_channel(int(x['thread_id'])) or await self.bot.fetch_channel(int(x['thread_id']))
            except discord.NotFound:
                await self.db.delete_one({'thread_id': x['thread_id'], 'guild': x['guild']})
                count += 1

        embed = discord.Embed(color=self.bot.main_color)
        embed.description = f"Cleaned up {count} closed tickets records"
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def unclaim(self, ctx):
        """Unclaim a thread"""
        embed = discord.Embed(color=self.bot.main_color)
        description = ""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(self.bot.modmail_guild.id)})
        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(self.bot.modmail_guild.id)}, {'$pull': {'claimers': str(ctx.author.id)}})
            description += 'Removed from claimers.\n'

        if str(ctx.thread.id) not in self.bot.config["subscriptions"]:
            self.bot.config["subscriptions"][str(ctx.thread.id)] = []

        mentions = self.bot.config["subscriptions"][str(ctx.thread.id)]

        if ctx.author.mention in
