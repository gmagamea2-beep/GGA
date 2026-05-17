import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import sqlite3
import random

# 디스코드 봇 설정 (모든 권한 허용)
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# 데이터베이스 초기화
conn = sqlite3.connect("gga_warn.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    user_id INTEGER PRIMARY KEY,
    warn_count INTEGER DEFAULT 0,
    last_warn_date TEXT
)
""")
conn.commit()

@bot.event
async def on_ready():
    print(f"[{bot.user.name}] GGA 군신 협치제 제재 시스템 가동.")
    await bot.tree.sync()
    auto_warn_deduction.start()

# [함수] 경고 수치에 따른 자동 제재 및 알림 시스템
async def check_and_execute_punishment(interaction: discord.Interaction, member: discord.Member, total_warns: int):
    if total_warns >= 30:
        embed = discord.Embed(title="💀 최고 제재 집행 (영구 차단)", color=discord.Color.red())
        embed.description = f"{member.mention} 유저가 **경고 {total_warns}회** 누적으로 인해 즉시 서버에서 **영구 차단(BAN)** 되었습니다."
        await interaction.channel.send(embed=embed)
        await member.ban(reason=f"GGA 규정 위반 - 경고 {total_warns}회 누적")
        
    elif total_warns >= 20:
        embed = discord.Embed(title="🔴 중등 제재 집행 (서버 강퇴)", color=0xff0000)
        embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달했습니다.\n\n⚠️ **[집행 지침]** 중각 회의 후 즉시 강퇴 처리 예정이며, 10일 후 그마 권한으로만 재가입이 가능합니다."
        await interaction.channel.send(embed=embed)
        await member.kick(reason=f"경고 {total_warns}회 누적 (20회 도달)")

    elif total_warns >= 14:
        embed = discord.Embed(title="🟠 경고 14회 도달 (서버 강퇴 7일)", color=0xffa500)
        embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달하여 서버에서 강퇴 처리되었습니다.\n\n📌 **[안내]** 우회 접속 시 기간이 초기화되며, 7일 후 중각이 제공하는 특별 링크로만 재입장 가능합니다."
        await interaction.channel.send(embed=embed)
        await member.kick(reason=f"경고 {total_warns}회 누적 (14회 도달)")

    elif total_warns >= 7:
        duration = datetime.timedelta(days=7)
        await member.timeout(duration, reason=f"경고 {total_warns}회 누적 (7회 도달)")
        embed = discord.Embed(title="🟡 경고 7회 도달 (타임아웃 7일)", color=0xffff00)
        embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달하여 일주일 동안 채팅 및 음성 채널 이용이 금지(타임아웃)되었습니다."
        await interaction.channel.send(embed=embed)

# 1. [/경고] 명령어
@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다 (중각 이상 권한)")
@app_commands.describe(유저="경고를 줄 유저 선택", 횟수="부여할 경고 횟수")
@commands.has_permissions(manage_messages=True)
async def give_warn(interaction: discord.Interaction, 유저: discord.Member, 횟수: int):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT warn_count FROM warnings WHERE user_id = ?", (유저.id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute("INSERT INTO warnings VALUES (?, ?, ?)", (유저.id, 횟수, current_time))
        total_warns = 횟수
    else:
        total_warns = row[0] + 횟수
        cursor.execute("UPDATE warnings SET warn_count = ?, last_warn_date = ? WHERE user_id = ?", (total_warns, current_time, 유저.id))
    conn.commit()
    
    await interaction.response.send_message(f"⚠️ **{유저.mention} 유저에게 경고 {횟수}회를 부여했습니다.** (현재 누적: {total_warns}회)\n📅 30일 모범 유저 타이머가 오늘부터 리셋됩니다.")
    await check_and_execute_punishment(interaction, 유저, total_warns)

# 2. [/강제처벌] 명령어
@bot.tree.command(name="강제처벌", description="유저에게 즉각적인 특수 처벌을 내립니다.")
@app_commands.describe(유저="처벌할 유저 선택", 처벌이름="처벌 종류 선택")
@app_commands.choices(처벌이름=[
    app_commands.Choice(name="타임아웃(채팅 금지)", value="timeout"),
    app_commands.Choice(name="중각 해임 및 유저로 변경", value="demote")
])
@commands.has_permissions(administrator=True)
async def force_punish(interaction: discord.Interaction, 유저: discord.Member, 처벌이름: str):
    if 처벌이름 == "timeout":
        await 유저.timeout(datetime.timedelta(days=3), reason="그마/중각 직권 강제 처벌")
        await interaction.response.send_message(f"🔨 **직권 처벌 집행:** {유저.mention} 유저에게 강제 타임아웃 처벌을 내렸습니다.")
    elif 처벌이름 == "demote":
        user_role = discord.utils.get(interaction.guild.roles, name="유저")
        if user_role is None:
            await interaction.response.send_message("❌ 서버에 '유저'라는 이름의 역할이 존재하지 않아 계급 강등을 실패했습니다.", ephemeral=True)
            return
        roles_to_remove = [r for r in 유저.roles if r.name in ["중각", "외각"]]
        await 유저.remove_roles(*roles_to_remove)
        await 유저.add_roles(user_role)
        await interaction.response.send_message(f"🛡️ **직권 계급 해임:** {유저.mention} 운영진의 권한을 박탈하고 일반 **[{user_role.name}]** 계급으로 강등 변경하였습니다.")

# 3. [자동 감시 시스템]
@tasks.loop(hours=24)
async def auto_warn_deduction():
    current_time = datetime.datetime.now()
    cursor.execute("SELECT user_id, warn_count, last_warn_date FROM warnings WHERE warn_count > 0")
    rows = cursor.fetchall()
    
    for row in rows:
        user_id, warn_count, last_warn_date_str = row
        last_warn_date = datetime.datetime.strptime(last_warn_date_str, "%Y-%m-%d %H:%M:%S")
        
        if current_time >= last_warn_date + datetime.timedelta(days=30):
            deduct = random.randint(1, 3)
            new_warn_count = max(0, warn_count - deduct)
            new_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("UPDATE warnings SET warn_count = ?, last_warn_date = ? WHERE user_id = ?", (new_warn_count, new_time_str, user_id))
    conn.commit()

# 봇 실행 (줄 맨 왼쪽에 딱 붙여두었습니다!)
bot.run("MTUwNTU0OTMxNzU2NDQwMzc3Mg.GK91Qb.RuzF0PaLMBBXTO6CKYBBty-SpswM9IKhyg8S0w")