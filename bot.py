import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ── 設定區 ────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "")          # Discord Bot Token
DATA_FILE = "data.json"                          # 資料儲存檔
TZ = ZoneInfo("Asia/Taipei")                     # 時區
# ─────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ══════════════════════════════════════════════
#  資料存取
# ══════════════════════════════════════════════
def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"employees": {}, "config": {"hourly": 183, "std_hours": 8, "ot1": 1.34, "ot2": 1.67, "labor": 0.9, "health": 5.17, "threshold": 100000}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_emp(data: dict, user_id: str) -> dict:
    if user_id not in data["employees"]:
        data["employees"][user_id] = {
            "name": "",
            "punched_in": None,       # ISO datetime string
            "records": [],            # list of attendance records
            "performance": [],        # list of {month, amount}
            "custom_hourly": None,    # unlocked custom rate
        }
    return data["employees"][user_id]


def now_tw() -> datetime:
    return datetime.now(TZ)


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y/%m/%d")


def fmt_hm(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60}m"


def get_rate(emp: dict, cfg: dict) -> float:
    return emp["custom_hourly"] if emp["custom_hourly"] else cfg["hourly"]


def total_perf(emp: dict) -> float:
    return sum(p["amount"] for p in emp.get("performance", []))


# ══════════════════════════════════════════════
#  Embed 顏色常數
# ══════════════════════════════════════════════
GREEN  = 0x1D9E75
AMBER  = 0xBA7517
RED    = 0xE24B4A
BLUE   = 0x378ADD
PURPLE = 0x7F77DD


# ══════════════════════════════════════════════
#  Bot 啟動
# ══════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot 已上線：{bot.user}  (同步 Slash Commands 完成)")


# ══════════════════════════════════════════════
#  /打卡上班
# ══════════════════════════════════════════════
@tree.command(name="打卡上班", description="上班打卡，開始計時工時")
async def punch_in(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)

    if emp["punched_in"]:
        already = datetime.fromisoformat(emp["punched_in"])
        embed = discord.Embed(
            title="⚠️ 您已打卡上班",
            description=f"上班時間：**{fmt_time(already)}**\n請先完成下班打卡。",
            color=AMBER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    now = now_tw()
    emp["punched_in"] = now.isoformat()
    emp["name"] = interaction.user.display_name
    save_data(data)

    embed = discord.Embed(title="✅ 上班打卡成功", color=GREEN)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="時間", value=fmt_time(now), inline=True)
    embed.add_field(name="日期", value=fmt_date(now), inline=True)
    embed.set_footer(text="記得下班前使用 /打卡下班")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════
#  /打卡下班
# ══════════════════════════════════════════════
@tree.command(name="打卡下班", description="下班打卡，結算今日工時")
async def punch_out(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)
    cfg = data["config"]

    if not emp["punched_in"]:
        embed = discord.Embed(title="⚠️ 尚未上班打卡", description="請先使用 `/打卡上班`", color=RED)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    now = now_tw()
    in_time = datetime.fromisoformat(emp["punched_in"])
    total_mins = int((now - in_time).total_seconds() // 60)
    std_mins = int(cfg["std_hours"] * 60)
    ot_mins = max(0, total_mins - std_mins)

    record = {
        "date": fmt_date(in_time),
        "in_time": fmt_time(in_time),
        "out_time": fmt_time(now),
        "total_mins": total_mins,
        "ot_mins": ot_mins,
    }
    emp["records"].append(record)
    emp["punched_in"] = None
    save_data(data)

    hourly = get_rate(emp, cfg)
    std_pay = round((min(total_mins, std_mins) / 60) * hourly)
    ot1m = min(ot_mins, 120)
    ot2m = max(0, ot_mins - 120)
    ot_pay = round((ot1m / 60) * hourly * cfg["ot1"] + (ot2m / 60) * hourly * cfg["ot2"])
    gross = std_pay + ot_pay

    status = "⏰ 加班" if ot_mins > 0 else ("⚠️ 工時不足" if total_mins < std_mins else "✅ 正常")

    embed = discord.Embed(title="🏁 下班打卡成功", color=BLUE)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="日期", value=fmt_date(in_time), inline=True)
    embed.add_field(name="狀態", value=status, inline=True)
    embed.add_field(name="上班", value=fmt_time(in_time), inline=True)
    embed.add_field(name="下班", value=fmt_time(now), inline=True)
    embed.add_field(name="總工時", value=fmt_hm(total_mins), inline=True)
    if ot_mins > 0:
        embed.add_field(name="加班時數", value=fmt_hm(ot_mins), inline=True)
    embed.add_field(name="今日薪資（稅前）", value=f"**${gross:,}**", inline=True)
    embed.add_field(name="使用時薪", value=f"${hourly}/hr {'🔓' if emp['custom_hourly'] else ''}", inline=True)
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════
#  /我的紀錄
# ══════════════════════════════════════════════
@tree.command(name="我的紀錄", description="查看自己的出勤紀錄（最近10筆）")
async def my_records(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)

    recs = emp["records"][-10:]
    if not recs:
        await interaction.response.send_message("📋 尚無打卡紀錄", ephemeral=True)
        return

    lines = []
    for r in reversed(recs):
        ot = f" (+{fmt_hm(r['ot_mins'])}加班)" if r["ot_mins"] > 0 else ""
        lines.append(f"`{r['date']}` {r['in_time']}→{r['out_time']}  **{fmt_hm(r['total_mins'])}**{ot}")

    embed = discord.Embed(title=f"📋 {interaction.user.display_name} 的出勤紀錄", description="\n".join(lines), color=PURPLE)
    embed.set_footer(text="顯示最近 10 筆")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════
#  /薪資結算
# ══════════════════════════════════════════════
@tree.command(name="薪資結算", description="結算本月薪資（個人）")
@app_commands.describe(month="指定月份 (格式: 2025/05)，留空為本月")
async def calc_salary(interaction: discord.Interaction, month: str = None):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)
    cfg = data["config"]

    now = now_tw()
    target = month if month else now.strftime("%Y/%m")
    recs = [r for r in emp["records"] if r["date"].startswith(target)]

    if not recs:
        await interaction.response.send_message(f"📭 {target} 無出勤紀錄", ephemeral=True)
        return

    hourly = get_rate(emp, cfg)
    days = len(recs)
    total_mins = sum(r["total_mins"] for r in recs)
    ot_mins = sum(r["ot_mins"] for r in recs)
    std_mins = total_mins - ot_mins

    std_pay = round((std_mins / 60) * hourly)
    ot1m = min(ot_mins, 120)
    ot2m = max(0, ot_mins - 120)
    ot_pay = round((ot1m / 60) * hourly * cfg["ot1"] + (ot2m / 60) * hourly * cfg["ot2"])
    gross = std_pay + ot_pay
    labor = round(gross * cfg["labor"] / 100)
    health = round(gross * cfg["health"] / 100)
    net = gross - labor - health

    perf = total_perf(emp)
    perf_txt = f"${perf:,} / ${cfg['threshold']:,}  {'🔓 達標' if perf >= cfg['threshold'] else '🔒 未達標'}"

    embed = discord.Embed(title=f"💰 {target} 薪資結算", color=GREEN)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="出勤天數", value=f"{days} 天", inline=True)
    embed.add_field(name="總工時", value=fmt_hm(total_mins), inline=True)
    embed.add_field(name="加班時數", value=fmt_hm(ot_mins), inline=True)
    embed.add_field(name="使用時薪", value=f"${hourly}/hr {'🔓個人' if emp['custom_hourly'] else '預設'}", inline=True)
    embed.add_field(name="累積業績", value=perf_txt, inline=True)
    embed.add_field(name="正常薪資", value=f"${std_pay:,}", inline=True)
    embed.add_field(name="加班費", value=f"${ot_pay:,}", inline=True)
    embed.add_field(name="應發總額", value=f"${gross:,}", inline=True)
    embed.add_field(name="勞保扣除", value=f"-${labor:,}", inline=True)
    embed.add_field(name="健保扣除", value=f"-${health:,}", inline=True)
    embed.add_field(name="🏆 實領薪資", value=f"**${net:,}**", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════
#  /登錄業績
# ══════════════════════════════════════════════
@tree.command(name="登錄業績", description="登錄個人業績金額")
@app_commands.describe(amount="業績金額（元）", month="月份 (格式: 2025/05)，留空為本月")
async def add_performance(interaction: discord.Interaction, amount: float, month: str = None):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)
    cfg = data["config"]

    now = now_tw()
    target = month if month else now.strftime("%Y/%m")

    existing = next((p for p in emp["performance"] if p["month"] == target), None)
    if existing:
        existing["amount"] = amount
    else:
        emp["performance"].append({"month": target, "amount": amount})

    save_data(data)

    perf = total_perf(emp)
    unlocked = perf >= cfg["threshold"]
    color = GREEN if unlocked else AMBER

    embed = discord.Embed(title="📊 業績已更新", color=color)
    embed.add_field(name="月份", value=target, inline=True)
    embed.add_field(name="本月業績", value=f"${amount:,.0f}", inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    embed.add_field(name="門檻", value=f"${cfg['threshold']:,}", inline=True)
    embed.add_field(name="狀態", value="🔓 已達標！可聯繫管理員解鎖個人時薪" if unlocked else f"🔒 距門檻還差 ${cfg['threshold']-perf:,.0f}", inline=True)
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════
#  /查詢業績
# ══════════════════════════════════════════════
@tree.command(name="查詢業績", description="查詢個人累積業績與解鎖狀態")
async def check_perf(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    emp = get_emp(data, uid)
    cfg = data["config"]

    perf = total_perf(emp)
    pct = min(100, round(perf / cfg["threshold"] * 100))
    unlocked = perf >= cfg["threshold"]
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

    embed = discord.Embed(title="📈 業績查詢", color=GREEN if unlocked else PURPLE)
    embed.add_field(name="員工", value=interaction.user.mention, inline=False)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    embed.add_field(name="門檻", value=f"${cfg['threshold']:,}", inline=True)
    embed.add_field(name="達成率", value=f"{pct}%", inline=True)
    embed.add_field(name="進度", value=f"`{bar}` {pct}%", inline=False)
    embed.add_field(name="時薪狀態", value=
        f"🔓 個人時薪 **${emp['custom_hourly']}/hr**" if emp["custom_hourly"] else
        ("🔓 達標！請聯繫管理員解鎖個人時薪" if unlocked else f"🔒 未達標，使用預設時薪 ${cfg['hourly']}/hr"),
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════
#  管理員指令
# ══════════════════════════════════════════════

def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


@tree.command(name="管理員_設定時薪", description="【管理員】解鎖員工個人時薪")
@app_commands.describe(member="員工", hourly="自訂時薪（元）")
@is_admin()
async def admin_set_rate(interaction: discord.Interaction, member: discord.Member, hourly: float):
    data = load_data()
    cfg = data["config"]
    uid = str(member.id)
    emp = get_emp(data, uid)

    perf = total_perf(emp)
    if perf < cfg["threshold"]:
        embed = discord.Embed(
            title="❌ 業績未達標",
            description=f"{member.mention} 累積業績 ${perf:,.0f}，尚未達門檻 ${cfg['threshold']:,}",
            color=RED,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    emp["custom_hourly"] = hourly
    save_data(data)

    embed = discord.Embed(title="✅ 個人時薪已設定", color=GREEN)
    embed.add_field(name="員工", value=member.mention, inline=True)
    embed.add_field(name="新時薪", value=f"${hourly}/hr", inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    await interaction.response.send_message(embed=embed)


@tree.command(name="管理員_設定門檻", description="【管理員】設定業績解鎖門檻")
@app_commands.describe(threshold="門檻金額（元）")
@is_admin()
async def admin_set_threshold(interaction: discord.Interaction, threshold: float):
    data = load_data()
    data["config"]["threshold"] = threshold
    save_data(data)
    embed = discord.Embed(title="✅ 門檻已更新", description=f"業績解鎖門檻設為 **${threshold:,.0f}**", color=GREEN)
    await interaction.response.send_message(embed=embed)


@tree.command(name="管理員_設定時薪預設", description="【管理員】設定全域預設時薪")
@app_commands.describe(hourly="時薪（元）")
@is_admin()
async def admin_set_default_rate(interaction: discord.Interaction, hourly: float):
    data = load_data()
    data["config"]["hourly"] = hourly
    save_data(data)
    embed = discord.Embed(title="✅ 預設時薪已更新", description=f"全域預設時薪設為 **${hourly}/hr**", color=GREEN)
    await interaction.response.send_message(embed=embed)


@tree.command(name="管理員_查看員工", description="【管理員】查看指定員工的資訊")
@app_commands.describe(member="員工")
@is_admin()
async def admin_view_emp(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    uid = str(member.id)
    emp = get_emp(data, uid)
    cfg = data["config"]

    recs = emp["records"]
    perf = total_perf(emp)
    hourly = get_rate(emp, cfg)
    total_mins = sum(r["total_mins"] for r in recs)

    embed = discord.Embed(title=f"👤 {member.display_name} 員工資訊", color=PURPLE)
    embed.add_field(name="出勤筆數", value=f"{len(recs)} 筆", inline=True)
    embed.add_field(name="累積工時", value=fmt_hm(total_mins), inline=True)
    embed.add_field(name="目前狀態", value="🟢 上班中" if emp["punched_in"] else "⚫ 下班中", inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    embed.add_field(name="使用時薪", value=f"${hourly}/hr {'🔓個人' if emp['custom_hourly'] else '預設'}", inline=True)
    embed.add_field(name="業績狀態", value="🔓 達標" if perf >= cfg["threshold"] else "🔒 未達標", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="管理員_月報表", description="【管理員】查看所有員工當月薪資報表")
@app_commands.describe(month="月份 (格式: 2025/05)，留空為本月")
@is_admin()
async def admin_monthly_report(interaction: discord.Interaction, month: str = None):
    data = load_data()
    cfg = data["config"]
    now = now_tw()
    target = month if month else now.strftime("%Y/%m")

    lines = []
    total_net = 0
    for uid, emp in data["employees"].items():
        recs = [r for r in emp["records"] if r["date"].startswith(target)]
        if not recs:
            continue
        hourly = get_rate(emp, cfg)
        total_mins = sum(r["total_mins"] for r in recs)
        ot_mins = sum(r["ot_mins"] for r in recs)
        std_mins = total_mins - ot_mins
        std_pay = round((std_mins / 60) * hourly)
        ot1m = min(ot_mins, 120)
        ot2m = max(0, ot_mins - 120)
        ot_pay = round((ot1m / 60) * hourly * cfg["ot1"] + (ot2m / 60) * hourly * cfg["ot2"])
        gross = std_pay + ot_pay
        labor = round(gross * cfg["labor"] / 100)
        health = round(gross * cfg["health"] / 100)
        net = gross - labor - health
        total_net += net
        name = emp.get("name") or f"UID:{uid[:6]}"
        rate_tag = "🔓" if emp["custom_hourly"] else ""
        lines.append(f"`{name}` {rate_tag} {len(recs)}天 {fmt_hm(total_mins)} → **${net:,}**")

    if not lines:
        await interaction.response.send_message(f"📭 {target} 無任何出勤紀錄", ephemeral=True)
        return

    embed = discord.Embed(title=f"📊 {target} 月薪報表", description="\n".join(lines), color=PURPLE)
    embed.add_field(name="合計薪資支出", value=f"**${total_net:,}**", inline=False)
    embed.set_footer(text="🔓 = 個人時薪（業績達標）")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════
#  錯誤處理
# ══════════════════════════════════════════════
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ 此指令需要管理員權限", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 發生錯誤：{error}", ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ 請設定環境變數 DISCORD_TOKEN")
        exit(1)
    bot.run(TOKEN)
