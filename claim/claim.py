import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.utils import match_user_id


class ClaimThread(commands.Cog):
    """Позволяет поддерживающим пользователям брать тикеты, отправляя команду claim в канале тикета"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        check_reply.fail_msg = 'Этот тикет был взят другим пользователем.'
        self.bot.get_command('reply').add_check(check_reply)
        self.bot.get_command('areply').add_check(check_reply)
        self.bot.get_command('fareply').add_check(check_reply)
        self.bot.get_command('freply').add_check(check_reply)
        
        # Добавляем параметр для канала уведомлений
        self.notification_channel_id = None  # Установите здесь ID вашего канала уведомлений

    async def check_claimer(self, ctx, claimer_id):
        config = await self.db.find_one({'_id': 'config'})
        if config and 'limit' in config:
            if config['limit'] == 0:
                return True
        else:
            raise commands.BadArgument(f"Сначала установите лимит. `{ctx.prefix}claim limit`")

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

    @commands.command()
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def claim(self, ctx):
        """Команда для взятия тикета"""
        claimer_id = str(ctx.author.id)
        channel_id = str(ctx.channel.id)

        if not await self.check_claimer(ctx, claimer_id):
            await ctx.send("Вы превысили лимит взятых тикетов.")
            return

        thread = await self.db.find_one({'thread_id': channel_id, 'guild': str(self.bot.modmail_guild.id)})
        if thread and 'claimers' in thread and len(thread['claimers']) != 0:
            await ctx.send("Этот тикет уже был взят.")
            return

        await self.db.find_one_and_update(
            {'thread_id': channel_id, 'guild': str(self.bot.modmail_guild.id)},
            {'$set': {'claimers': [claimer_id]}},
            upsert=True
        )

        embed = discord.Embed(
            title="Тикет взят",
            description=f"{ctx.author.mention} взял тикет.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Уведомление в заданный канал
        if self.notification_channel_id:
            notification_channel = self.bot.get_channel(self.notification_channel_id)
            if notification_channel:
                await notification_channel.send(f"{ctx.author.mention} взял тикет {ctx.channel.name}.")

    @commands.group(name='claim_bypass', invoke_without_command=True)
    async def claim_bypass_(self, ctx):
        """Управление ролями обхода проверки взятия тикета"""
        await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.guild_only()
    @claim_bypass_.command(name='add')
    async def claim_bypass_add(self, ctx, *bypass_roles: discord.Role):
        """Добавить роль для обхода проверки взятия тикета"""
        config = await self.db.find_one({'_id': 'config'})
        if not config:
            await self.db.insert_one({'_id': 'config', 'bypass_roles': [r.id for r in bypass_roles]})
        else:
            await self.db.find_one_and_update({'_id': 'config'}, {'$addToSet': {'bypass_roles': {'$each': [r.id for r in bypass_roles]}}})

        added = ", ".join(f"`{r.name}`" for r in bypass_roles)
        await ctx.send(f'**Добавлены роли для обхода проверки**:\n{added}')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    @claim_bypass_.command(name='remove')
    async def claim_bypass_remove(self, ctx, role: discord.Role):
        """Удалить роль для обхода проверки взятия тикета"""
        config = await self.db.find_one({'_id': 'config'})
        if config and 'bypass_roles' in config and role.id in config['bypass_roles']:
            await self.db.find_one_and_update({'_id': 'config'}, {'$pull': {'bypass_roles': role.id}})
            await ctx.send(f'**Удалена роль для обхода проверки**:\n`{role.name}`')
        else:
            await ctx.send(f'`{role.name}` не находится в списке ролей для обхода проверки')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def overridereply(self, ctx, *, msg: str = ""):
        """Позволяет модераторам обходить проверку взятия тикета при ответе"""
        await ctx.invoke(self.bot.get_command('reply'), msg=msg)


async def check_reply(ctx):
    thread = await ctx.bot.get_cog('ClaimThread').db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.bot.modmail_guild.id)})
    if thread and len(thread['claimers']) != 0:
        in_role = False
        config = await ctx.bot.get_cog('ClaimThread').db.find_one({'_id': 'config'})
        if config and 'bypass_roles' in config:
            roles = [ctx.guild.get_role(r) for r in config['bypass_roles'] if ctx.guild.get_role(r) is not None]
            for role in roles:
                if role in ctx.author.roles:
                    in_role = True
        return ctx.author.bot or in_role or str(ctx.author.id) in thread['claimers']
    return True


async def setup(bot):
    await bot.add_cog(ClaimThread(bot))
