import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import random
import os
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- [포트 가변화] Koyeb 및 외부 호스팅 포트 대응 웹서버 ---
app = Flask('')

@app.route('/')
def home():
    return "GGA Bot is Online! 24/7 MongoDB Guard Active."

def run():
    # Koyeb은 환경에 따라 포트를 유동적으로 잡으므로 os.environ에서 PORT를 가져옵니다. (기본값 8000)
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
# ----------------------------------------------------

# 디스코드 봇 설정
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- [신규] MongoDB Atlas 클라우드 데이터베이스 초기화 ---
MONGO_URI = os.environ.get("MONGO_URI")
if MONGO_URI:
    try:
        client = MongoClient(MONGO_URI)
        db = client['gga_warn_db']
        warn_coll = db['warnings']         # 경고 데이터 컬렉션
        punish_coll = db['punishments']     # 처벌 기준 컬렉션
        print("✅ MongoDB Atlas 클라우드 DB 연결 성공!")
        
        # 기본 처벌 설정 세팅 (DB가 비어있을 때만 최초 입력)
        if punish_coll.count_documents({}) == 0:
            default_settings = [
                {"_id": 1, "warn_required": 7, "punish_type": "timeout", "description": "타임아웃 7일"},
                {"_id": 2, "warn_required": 14, "punish_type": "kick_7", "description": "서버 강퇴 7일"},
                {"_id": 3, "warn_required": 20, "punish_type": "kick_meeting", "description": "중각 회의 후 강퇴"},
                {"_id": 4, "warn_required": 30, "punish_type": "ban", "description": "영구 차단(BAN)"}
            ]
            punish_coll.insert_many(default_settings)
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        warn_coll, punish_coll = None, None
else:
    print("⚠️ MONGO_URI 환경변수가 없습니다. DB 기능이 제한됩니다.")
    warn_coll, punish_coll = None, None


@bot.event
async def on_ready():
    print(f"[{bot.user.name}] GGA 군신 협치제 제재 시스템 2.5 (MongoDB) 가동.")
    try:
        await bot.tree.sync()
        print("✅ 슬래시 명령어 동기화 완료!")
    except Exception as e:
        print(f"❌ 슬래시 동기화 실패: {e}")
    auto_warn_deduction.start()


# 유동적 처벌 집행 함수 (MongoDB 버전으로 리팩토링)
async def check_and_execute_punishment(interaction: discord.Interaction, member: discord.Member, total_warns: int):
    if not punish_coll: return
    
    # 필요한 경고 컷수가 높은 순서대로 정렬해서 가져옴
    settings = list(punish_coll.find().sort("warn_required", -1))
    
    for setting in settings:
        warn_required = setting["warn_required"]
        punish_type = setting["punish_type"]
        description = setting["description"]
        
        if total_warns >= warn_required:
            if punish_type == 'ban':
                embed = discord.Embed(title="💀 최고 제재 집행 (영구 차단)", color=discord.Color.red())
                embed.description = f"{member.mention} 유저가 **경고 {total_warns}회** 누적으로 인해 즉시 서버에서 **영구 차단(BAN)** 되었습니다.\n기준: {description}"
                await interaction.channel.send(embed=embed)
                await member.ban(reason=f"GGA 규정 위반 - 경고 {total_warns}회 누적")
                return
            elif punish_type == 'kick_meeting':
                embed = discord.Embed(title="🔴 중등 제재 집행 (서버 강퇴)", color=0xff0000)
                embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달했습니다.\n\n⚠️ **[집행 지침]** 중각 회의 후 즉시 강퇴 처리 예정이며, 10일 후 그마 권한으로만 재가입이 가능합니다.\n기준: {description}"
                await interaction.channel.send(embed=embed)
                await member.kick(reason=f"경고 {total_warns}회 누적")
                return
            elif punish_type == 'kick_7':
                embed = discord.Embed(title="🟠 경고 도달 (서버 강퇴 7일)", color=0xffa500)
                embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달하여 서버에서 강퇴 처리되었습니다.\n\n📌 **[안내]** 7일 후 중각이 제공하는 특별 링크로만 재입장 가능합니다.\n기준: {description}"
                await interaction.channel.send(embed=embed)
                await member.kick(reason=f"경고 {total_warns}회 누적")
                return
            elif punish_type == 'timeout':
                duration = datetime.timedelta(days=7)
                await member.timeout(duration, reason=f"경고 {total_warns}회 누적")
                embed = discord.Embed(title="🟡 경고 도달 (타임아웃 7일)", color=0xffff00)
                embed.description = f"{member.mention} 유저가 **경고 {total_warns}회**에 도달하여 일주일 동안 채팅 및 음성 이용이 금지되었습니다.\n기준: {description}"
                await interaction.channel.send(embed=embed)
                return

# 1. [/경고] 명령어 (사유 입력 추가)
@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다 (중각 이상 권한)")
@app_commands.describe(유저="경고를 줄 유저 선택", 횟수="부여할 경고 횟수", 사유="경고 사유를 적어주세요")
@app_commands.checks.has_permissions(manage_messages=True) # 슬래시 전용 권한 체크로 수정
async def give_warn(interaction: discord.Interaction, 유저: discord.Member, 횟수: int, 사유: str = "사유 미작성"):
    if not warn_coll:
        await interaction.response.send_message("❌ DB 연결 안 됨", ephemeral=True)
        return
        
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = str(유저.id)
    
    # 복수 횟수 처리를 고려하여 사유 문구 생성
    reason_entry = f"{사유} (필드에서 경고 {횟수}회 부여됨)"
    
    # DB 업데이트 (없으면 생성, 있으면 증가 및 사유 push)
    warn_coll.update_one(
        {"_id": user_id},
        {
            "$inc": {"warn_count": 횟수},
            "$set": {"last_warn_date": current_time},
            "$push": {"reasons": {"$each": [reason_entry] * 횟수}} # 횟수만큼 사유 칸 생성
        },
        upsert=True
    )
    
    user_data = warn_coll.find_one({"_id": user_id})
    total_warns = user_data["warn_count"]
    
    await interaction.response.send_message(f"⚠️ **{유저.mention} 유저에게 경고 {횟수}회를 부여했습니다.** (현재 누적: {total_warns}회)\n📝 사유: `{사유}`\n📅 30일 모범 유저 타이머가 리셋됩니다.")
    await check_and_execute_punishment(interaction, 유저, total_warns)

# 2. [/경고확인] 명령어 (점 리스트 출력 업그레이드)
@bot.tree.command(name="경고확인", description="특정 유저의 경고 수치와 상세 사유 리스트를 확인합니다.")
@app_commands.describe(유저="조회할 유저 선택")
async def check_warn(interaction: discord.Interaction, 유저: discord.Member):
    if not warn_coll: return
    
    user_id = str(유저.id)
    user_data = warn_coll.find_one({"_id": user_id})
    
    if not user_data or user_data.get("warn_count", 0) == 0:
        await interaction.response.send_message(f"✅ {유저.mention} 유저는 현재 누적된 경고가 없는 깨끗한 모범 유저입니다.")
    else:
        warn_count = user_data["warn_count"]
        last_date = user_data["last_warn_date"]
        reasons = user_data.get("reasons", [])
        
        embed = discord.Embed(title=f"📋 {유저.display_name} 유저 제재 상태 보고서", color=0x00ff00)
        embed.add_field(name="⚠️ 누적 경고 횟수", value=f"**{warn_count}회**", inline=True)
        embed.add_field(name="📅 마지막 갱신일", value=f"{last_date}", inline=True)
        
        # 상세 사유를 점(・) 리스트 양식으로 변환
        if reasons:
            reason_text = "\n".join([f"・ {i+1}. {r}" for i, r in enumerate(reasons)])
            # 임베드 글자수 제한 방지
            if len(reason_text) > 1024: reason_text = reason_text[:1000] + "\n...이하 생략"
            embed.add_field(name="📝 누적된 처벌 사유 내역", value=reason_text, inline=False)
        else:
            embed.add_field(name="📝 누적된 처벌 사유 내역", value="・ 기록된 사유가 없습니다.", inline=False)
            
        await interaction.response.send_message(embed=embed)

# 3. [/경고목록] 명령어
@bot.tree.command(name="경고목록", description="서버 내에서 경고를 1회 이상 받은 모든 유저의 리스트를 출력합니다.")
@app_commands.checks.has_permissions(manage_messages=True)
async def list_warns(interaction: discord.Interaction):
    if not warn_coll: return
    
    # 경고가 0보다 큰 유저들을 내림차순 정렬하여 가져옴
    rows = list(warn_coll.find({"warn_count": {"$gt": 0}}).sort("warn_count", -1))
    
    if not rows:
        await interaction.response.send_message("🕊️ 현재 서버에 경고를 받은 유저가 단 한 명도 없습니다! 평화로운 상태입니다.")
        return
        
    embed = discord.Embed(title="🚨 GGA 서버 블랙리스트 (경고 누적 명단)", color=0x000000)
    description_text = ""
    
    for index, row in enumerate(rows, start=1):
        member = interaction.guild.get_member(int(row["_id"]))
        member_name = member.mention if member else f"서버를 나간 유저({row['_id']})"
        description_text += f"**{index}위.** {member_name} — ⚠️ **{row['warn_count']}회**\n"
        
    embed.description = description_text
    await interaction.response.send_message(embed=embed)

# 4. [/경고차감] 명령어 (차감 시 최신 사유 기록도 같이 삭제되도록 업그레이드)
@bot.tree.command(name="경고차감", description="잘못 부여했거나 반성한 유저의 경고를 깎아줍니다 (중각 이상 권한)")
@app_commands.describe(유저="경고를 깎아줄 유저 선택", 횟수="차감할 경고 횟수")
@app_commands.checks.has_permissions(manage_messages=True)
async def remove_warn(interaction: discord.Interaction, 유저: discord.Member, 횟수: int):
    if not warn_coll: return
    
    user_id = str(유저.id)
    user_data = warn_coll.find_one({"_id": user_id})
    
    if not user_data or user_data.get("warn_count", 0) == 0:
        await interaction.response.send_message(f"❌ {유저.mention} 유자는 깎을 경고가 없습니다 (현재 0회)", ephemeral=True)
        return
        
    current_warns = user_data["warn_count"]
    reasons = user_data.get("reasons", [])
    
    new_warns = max(0, current_warns - 횟수)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 차감한 횟수만큼 최신 사유 뒤에서부터 제거
    for _ in range(min(횟수, len(reasons))):
        reasons.pop()
        
    if new_warns == 0:
        # 경고가 0이 되면 DB 도큐먼트를 깔끔하게 비워줌 (초기화)
        warn_coll.delete_one({"_id": user_id})
    else:
        warn_coll.update_one(
            {"_id": user_id},
            {"$set": {"warn_count": new_warns, "last_warn_date": current_time, "reasons": reasons}}
        )
        
    await interaction.response.send_message(f"💚 **사면 집행:** {유저.mention} 유저의 경고를 {횟수}회 차감했습니다. (현재 누적: {new_warns}회)")

# 5. [/처벌변경] 명령어
@bot.tree.command(name="처벌변경", description="경고 수치에 따른 처벌 기준 시스템을 수정합니다 (그마 전용 권한)")
@app_commands.describe(단계="수정할 처벌 단계 선택", 필요한경고수="처벌이 내려질 경고 컷수")
@app_commands.choices(단계=[
    app_commands.Choice(name="1단계 (노랑-타임아웃)", value=1),
    app_commands.Choice(name="2단계 (주황-강퇴7일)", value=2),
    app_commands.Choice(name="3단계 (빨강-회의강퇴)", value=3),
    app_commands.Choice(name="4단계 (해골-영구차단)", value=4)
])
@app_commands.checks.has_permissions(administrator=True)
async def change_punishment(interaction: discord.Interaction, 단계: int, 필요한경고수: int):
    if not punish_coll: return
    
    punish_coll.update_one({"_id": 단계}, {"$set": {"warn_required": 필요한경고수}})
    
    names = {1: "1단계 (타임아웃)", 2: "2단계 (서버강퇴 7일)", 3: "3단계 (중각회의 후 강퇴)", 4: "4단계 (영구 차단)"}
    await interaction.response.send_message(f"⚙️ **군신 협치제 법률 개정:** 이제부터 **[{names[단계]}]** 처벌 기준이 누적 경고 **{필요한경고수}회** 이상일 때로 변경됩니다.")

# 6. [/강제처벌] 명령어
@bot.tree.command(name="강제처벌", description="유저에게 즉각적인 특수 처벌을 내립니다.")
@app_commands.describe(유저="처벌할 유저 선택", 처벌이름="처벌 종류 선택")
@app_commands.choices(처벌이름=[
    app_commands.Choice(name="타임아웃(채팅 금지)", value="timeout"),
    app_commands.Choice(name="중각 해임 및 유저로 변경", value="demote")
])
@app_commands.checks.has_permissions(administrator=True)
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
        await r_user = 유저.add_roles(user_role)
        await interaction.response.send_message(f"🛡️ **직권 계급 해임:** {유저.mention} 운영진의 권한을 박탈하고 일반 **[{user_role.name}]** 계급으로 강등 변경하였습니다.")

# 7. [자동 감시 시스템] (MongoDB 스케줄러로 변경)
@tasks.loop(hours=24)
async def auto_warn_deduction():
    if not warn_coll: return
    
    current_time = datetime.datetime.now()
    rows = list(warn_coll.find({"warn_count": {"$gt": 0}}))
    
    for row in rows:
        user_id = row["_id"]
        warn_count = row["warn_count"]
        last_warn_date_str = row["last_warn_date"]
        reasons = row.get("reasons", [])
        
        last_warn_date = datetime.datetime.strptime(last_warn_date_str, "%Y-%m-%d %H:%M:%S")
        
        # 마지막 경고일로부터 30일이 지났다면 자동 차감 실행
        if current_time >= last_warn_date + datetime.timedelta(days=30):
            deduct = random.randint(1, 3)
            new_warn_count = max(0, warn_count - deduct)
            new_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 사유 리스트도 차감된 개수만큼 삭제
            for _ in range(min(deduct, len(reasons))):
                reasons.pop()
                
            if new_warn_count == 0:
                warn_coll.delete_one({"_id": user_id})
            else:
                warn_coll.update_one(
                    {"_id": user_id},
                    {"$set": {"warn_count": new_warn_count, "last_warn_date": new_time_str, "reasons": reasons}}
                )


# --- [글로벌 슬래시 에러 핸들러] 권한이 없는 일반유저가 명령어 침묵 방지 ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ 이 명령어를 사용할 관리자 권한(메시지 관리 권한 이상)이 없습니다.", ephemeral=True)
    else:
        print(f"⚠️ 슬래시 명령어 실행 중 알 수 없는 오류 발생: {error}")


# [보안 절대 사수] 웹서버 구동 후 디스코드 로그인 진행
keep_alive()
bot.run(os.environ['DISCORD_TOKEN'])
