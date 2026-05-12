import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

TOKEN     = os.getenv("DISCORD_TOKEN", "")
DATA_FILE = "data.json"
TZ        = ZoneInfo("Asia/Taipei")

intents = discord.Intents.default()
intents.message_content = True
bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

DEFAULT_CFG = {
    "part_hourly": 183,
    "std_hours":   8,
    "labor":       0.9,
    "health":      5.17,
    "pension":     6.0,
    "threshold":   100000
}

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"employees": {}, "config": DEFAULT_CFG.copy()}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in DEFAULT_CFG.items():
        data["config"].setdefault(k, v)
    return data

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_emp(data: dict, uid: str) -> dict:
    if uid not in data["employees"]:
        data["employees"][uid] = {
            "name": "", "type": "part",
            "monthly_salary": None, "hourly": None,
            "punched_in": None, "records": [],
            "performance": [], "custom_hourly": None,
        }
    return data["employees"][uid]

def now_tw() -> datetime:
    return datetime.now(TZ)

def fmt_time(dt): return dt.strftime("%H:%M:%S")
def fmt_date(dt): return dt.strftime("%Y/%m/%d")
def fmt_hm(m):    return f"{m//60}h {m%60}m"

def total_perf(emp):
    return sum(p["amount"] for p in emp.get("performance", []))

def get_part_rate(emp, cfg):
    return emp.get("custom_hourly") or emp.get("hourly") or cfg["part_hourly"]

def working_days_in_month(year, month):
    _, days = calendar.monthrange(year, month)
    return sum(1 for d in range(1, days+1) if datetime(year, month, d).weekday() < 5)

def calc_deductions(gross, cfg):
    labor   = round(gross * cfg["labor"]   / 100)
    health  = round(gross * cfg["health"]  / 100)
    pension = round(gross * cfg["pension"] / 100)
    return labor, health, pension, gross - labor - health

GREEN=0x1D9E75; AMBER=0xBA7517; RED=0xE24B4A; BLUE=0x378ADD; PURPLE=0x7F77DD

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot 已上線：{bot.user}（Slash Commands 已同步）")

@tree.command(name="打卡上班", description="上班打卡，開始計時")
async def punch_in(interaction: discord.Interaction):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid)
    if emp["punched_in"]:
        already = datetime.fromisoformat(emp["punched_in"])
        embed = discord.Embed(title="⚠️ 您已打卡上班", description=f"上班時間：**{fmt_time(already)}**\n請先完成下班打卡。", color=AMBER)
        await interaction.response.send_message(embed=embed, ephemeral=True); return
    now = now_tw(); today_str = fmt_date(now)
    already_today = [r for r in emp["records"] if r["date"] == today_str]
    if already_today:
        r = already_today[-1]
        embed = discord.Embed(title="⚠️ 今日已打卡過", description=f"上班 **{r['in_time']}** → 下班 **{r['out_time']}**\n工時 **{fmt_hm(r['total_mins'])}**\n如需修正請聯繫管理員。", color=AMBER)
        await interaction.response.send_message(embed=embed, ephemeral=True); return
    emp["punched_in"] = now.isoformat(); emp["name"] = interaction.user.display_name
    save_data(data)
    emp_type = "👔 正職" if emp["type"] == "full" else "🕐 兼職"
    embed = discord.Embed(title="✅ 上班打卡成功", color=GREEN)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="類型", value=emp_type, inline=True)
    embed.add_field(name="時間", value=fmt_time(now), inline=True)
    embed.add_field(name="日期", value=fmt_date(now), inline=True)
    embed.set_footer(text="記得下班前使用 /打卡下班")
    await interaction.response.send_message(embed=embed)

@tree.command(name="打卡下班", description="下班打卡，結算今日工時")
async def punch_out(interaction: discord.Interaction):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid); cfg = data["config"]
    if not emp["punched_in"]:
        today_str = fmt_date(now_tw()); already_today = [r for r in emp["records"] if r["date"] == today_str]
        if already_today:
            r = already_today[-1]
            embed = discord.Embed(title="⚠️ 今日已完成打卡", description=f"上班 **{r['in_time']}** → 下班 **{r['out_time']}**\n工時 **{fmt_hm(r['total_mins'])}**", color=AMBER)
        else:
            embed = discord.Embed(title="⚠️ 尚未上班打卡", description="請先使用 `/打卡上班`", color=RED)
        await interaction.response.send_message(embed=embed, ephemeral=True); return
    now = now_tw(); in_time = datetime.fromisoformat(emp["punched_in"])
    total_mins = int((now - in_time).total_seconds() // 60)
    emp["records"].append({"date": fmt_date(in_time), "in_time": fmt_time(in_time), "out_time": fmt_time(now), "total_mins": total_mins})
    emp["punched_in"] = None; save_data(data)
    embed = discord.Embed(title="🏁 下班打卡成功", color=BLUE)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="日期", value=fmt_date(in_time), inline=True)
    embed.add_field(name="工時", value=fmt_hm(total_mins), inline=True)
    embed.add_field(name="上班", value=fmt_time(in_time), inline=True)
    embed.add_field(name="下班", value=fmt_time(now), inline=True)
    if emp["type"] == "full":
        std = cfg["std_hours"] * 60
        embed.add_field(name="狀態", value="⚠️ 工時不足" if total_mins < std else "✅ 正常出勤", inline=True)
        embed.set_footer(text="正職月薪請用 /薪資結算 查看本月結算")
    else:
        hourly = get_part_rate(emp, cfg); today_pay = round((total_mins / 60) * hourly)
        _, _, _, net = calc_deductions(today_pay, cfg)
        embed.add_field(name="今日薪資（稅前）", value=f"**${today_pay:,}**", inline=True)
        embed.add_field(name="實領（扣勞健保）", value=f"**${net:,}**", inline=True)
        embed.add_field(name="使用時薪", value=f"${hourly}/hr", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="我的紀錄", description="查看自己的出勤紀錄（最近10筆）")
async def my_records(interaction: discord.Interaction):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid); cfg = data["config"]
    recs = emp["records"][-10:]
    if not recs:
        await interaction.response.send_message("📋 尚無打卡紀錄", ephemeral=True); return
    lines = []
    for r in reversed(recs):
        if emp["type"] == "full":
            lines.append(f"`{r['date']}` {r['in_time']}→{r['out_time']}  **{fmt_hm(r['total_mins'])}**  👔")
        else:
            pay = round((r["total_mins"] / 60) * get_part_rate(emp, cfg))
            lines.append(f"`{r['date']}` {r['in_time']}→{r['out_time']}  **{fmt_hm(r['total_mins'])}**  ${pay:,}")
    emp_type = "👔 正職" if emp["type"] == "full" else "🕐 兼職"
    embed = discord.Embed(title=f"📋 {interaction.user.display_name} 的出勤紀錄  {emp_type}", description="\n".join(lines), color=PURPLE)
    embed.set_footer(text="顯示最近 10 筆")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="薪資結算", description="結算指定月份薪資（個人）")
@app_commands.describe(month="月份 格式 2025/05，留空為本月")
async def calc_salary(interaction: discord.Interaction, month: str = None):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid); cfg = data["config"]
    now = now_tw(); target = month if month else now.strftime("%Y/%m")
    recs = [r for r in emp["records"] if r["date"].startswith(target)]
    if not recs:
        await interaction.response.send_message(f"📭 {target} 無出勤紀錄", ephemeral=True); return
    days = len(recs); total_mins = sum(r["total_mins"] for r in recs)
    try: y, m = int(target[:4]), int(target[5:7])
    except: await interaction.response.send_message("❌ 月份格式錯誤，請用 2025/05", ephemeral=True); return
    embed = discord.Embed(title=f"💰 {target} 薪資結算", color=GREEN)
    embed.add_field(name="員工", value=interaction.user.mention, inline=True)
    embed.add_field(name="出勤天數", value=f"{days} 天", inline=True)
    embed.add_field(name="總工時", value=fmt_hm(total_mins), inline=True)
    if emp["type"] == "full":
        monthly = emp.get("monthly_salary")
        if not monthly:
            embed.add_field(name="⚠️ 尚未設定月薪", value="請聯繫管理員使用 `/管理員_設定員工` 設定月薪", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True); return
        work_days = working_days_in_month(y, m)
        gross = round((monthly / work_days) * days)
        labor, health, pension, net = calc_deductions(gross, cfg)
        embed.add_field(name="類型", value="👔 正職月薪制", inline=True)
        embed.add_field(name="月薪", value=f"${monthly:,}", inline=True)
        embed.add_field(name="當月工作日", value=f"{work_days} 天", inline=True)
        embed.add_field(name="應發薪資", value=f"${gross:,}", inline=True)
        embed.add_field(name="勞保扣除", value=f"-${labor:,} ({cfg['labor']}%)", inline=True)
        embed.add_field(name="健保扣除", value=f"-${health:,} ({cfg['health']}%)", inline=True)
        embed.add_field(name="🏆 實領薪資", value=f"**${net:,}**", inline=True)
        embed.add_field(name="勞退提撥（雇主）", value=f"${pension:,} ({cfg['pension']}%)", inline=True)
    else:
        hourly = get_part_rate(emp, cfg)
        gross = round((total_mins / 60) * hourly)
        labor, health, pension, net = calc_deductions(gross, cfg)
        perf = total_perf(emp); perf_tag = "🔓 達標" if perf >= cfg["threshold"] else "🔒 未達標"
        rate_tag = "🔓個人" if emp.get("custom_hourly") else "預設"
        embed.add_field(name="類型", value="🕐 兼職時薪制", inline=True)
        embed.add_field(name="使用時薪", value=f"${hourly}/hr {rate_tag}", inline=True)
        embed.add_field(name="累積業績", value=f"${perf:,.0f}  {perf_tag}", inline=True)
        embed.add_field(name="應發薪資", value=f"${gross:,}", inline=True)
        embed.add_field(name="勞保扣除", value=f"-${labor:,} ({cfg['labor']}%)", inline=True)
        embed.add_field(name="健保扣除", value=f"-${health:,} ({cfg['health']}%)", inline=True)
        embed.add_field(name="🏆 實領薪資", value=f"**${net:,}**", inline=True)
        embed.add_field(name="勞退提撥（雇主）", value=f"${pension:,} ({cfg['pension']}%)", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="登錄業績", description="登錄個人業績金額")
@app_commands.describe(amount="業績金額（元）", month="月份 格式 2025/05，留空為本月")
async def add_performance(interaction: discord.Interaction, amount: float, month: str = None):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid); cfg = data["config"]
    now = now_tw(); target = month if month else now.strftime("%Y/%m")
    existing = next((p for p in emp["performance"] if p["month"] == target), None)
    if existing: existing["amount"] = amount
    else: emp["performance"].append({"month": target, "amount": amount})
    save_data(data)
    perf = total_perf(emp); unlocked = perf >= cfg["threshold"]
    embed = discord.Embed(title="📊 業績已更新", color=GREEN if unlocked else AMBER)
    embed.add_field(name="月份", value=target, inline=True)
    embed.add_field(name="本月業績", value=f"${amount:,.0f}", inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    embed.add_field(name="狀態", value="🔓 已達標！可聯繫管理員解鎖個人時薪" if unlocked else f"🔒 距門檻還差 ${cfg['threshold']-perf:,.0f}", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="查詢業績", description="查詢個人累積業績與解鎖狀態")
async def check_perf(interaction: discord.Interaction):
    data = load_data(); uid = str(interaction.user.id); emp = get_emp(data, uid); cfg = data["config"]
    perf = total_perf(emp); pct = min(100, round(perf / cfg["threshold"] * 100))
    unlocked = perf >= cfg["threshold"]; bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    embed = discord.Embed(title="📈 業績查詢", color=GREEN if unlocked else PURPLE)
    embed.add_field(name="員工", value=interaction.user.mention, inline=False)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    embed.add_field(name="門檻", value=f"${cfg['threshold']:,}", inline=True)
    embed.add_field(name="達成率", value=f"{pct}%", inline=True)
    embed.add_field(name="進度", value=f"`{bar}` {pct}%", inline=False)
    embed.add_field(name="時薪狀態", value=(f"🔓 個人時薪 **${emp['custom_hourly']}/hr**" if emp.get("custom_hourly") else "🔓 達標！請聯繫管理員解鎖" if unlocked else f"🔒 未達標，預設時薪 ${cfg['part_hourly']}/hr"), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@tree.command(name="管理員_設定員工", description="【管理員】設定員工類型與薪資")
@app_commands.describe(member="員工", emp_type="員工類型", salary="正職月薪（元）", hourly="兼職時薪（元）")
@app_commands.choices(emp_type=[app_commands.Choice(name="👔 正職（月薪制）", value="full"), app_commands.Choice(name="🕐 兼職（時薪制）", value="part")])
@is_admin()
async def admin_set_employee(interaction: discord.Interaction, member: discord.Member, emp_type: str, salary: float = None, hourly: float = None):
    data = load_data(); uid = str(member.id); emp = get_emp(data, uid)
    emp["type"] = emp_type; emp["name"] = member.display_name
    if emp_type == "full":
        if salary is None:
            await interaction.response.send_message("❌ 正職請填寫月薪金額", ephemeral=True); return
        emp["monthly_salary"] = salary; desc = f"類型：👔 正職月薪制\n月薪：**${salary:,.0f}**"
    else:
        emp["hourly"] = hourly; cfg = data["config"]
        display_rate = hourly or cfg["part_hourly"]; desc = f"類型：🕐 兼職時薪制\n時薪：**${display_rate}/hr**"
    save_data(data)
    embed = discord.Embed(title=f"✅ {member.display_name} 員工設定完成", description=desc, color=GREEN)
    await interaction.response.send_message(embed=embed)

@tree.command(name="管理員_設定時薪", description="【管理員】解鎖兼職員工個人時薪（需業績達標）")
@app_commands.describe(member="員工", hourly="自訂時薪（元）")
@is_admin()
async def admin_set_rate(interaction: discord.Interaction, member: discord.Member, hourly: float):
    data = load_data(); cfg = data["config"]; uid = str(member.id); emp = get_emp(data, uid)
    if emp["type"] != "part":
        await interaction.response.send_message("❌ 此指令僅適用兼職員工，正職月薪請用 `/管理員_設定員工`", ephemeral=True); return
    perf = total_perf(emp)
    if perf < cfg["threshold"]:
        embed = discord.Embed(title="❌ 業績未達標", description=f"{member.mention} 累積業績 ${perf:,.0f}，尚未達門檻 ${cfg['threshold']:,}", color=RED)
        await interaction.response.send_message(embed=embed, ephemeral=True); return
    emp["custom_hourly"] = hourly; save_data(data)
    embed = discord.Embed(title="✅ 個人時薪已解鎖", color=GREEN)
    embed.add_field(name="員工", value=member.mention, inline=True)
    embed.add_field(name="新時薪", value=f"${hourly}/hr", inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="管理員_設定費率", description="【管理員】調整勞保、健保、勞退費率")
@app_commands.describe(labor="勞保費率 %（預設 0.9）", health="健保費率 %（預設 5.17）", pension="勞退提撥 %（預設 6.0）")
@is_admin()
async def admin_set_fees(interaction: discord.Interaction, labor: float = None, health: float = None, pension: float = None):
    data = load_data(); cfg = data["config"]; changed = []
    if labor   is not None: cfg["labor"]   = labor;   changed.append(f"勞保：**{labor}%**")
    if health  is not None: cfg["health"]  = health;  changed.append(f"健保：**{health}%**")
    if pension is not None: cfg["pension"] = pension; changed.append(f"勞退：**{pension}%**")
    if not changed:
        await interaction.response.send_message("⚠️ 請至少填寫一個費率", ephemeral=True); return
    save_data(data)
    embed = discord.Embed(title="✅ 費率已更新", description="\n".join(changed), color=GREEN)
    embed.set_footer(text=f"目前：勞保 {cfg['labor']}%  健保 {cfg['health']}%  勞退 {cfg['pension']}%")
    await interaction.response.send_message(embed=embed)

@tree.command(name="管理員_設定門檻", description="【管理員】設定業績解鎖門檻")
@app_commands.describe(threshold="門檻金額（元）")
@is_admin()
async def admin_set_threshold(interaction: discord.Interaction, threshold: float):
    data = load_data(); data["config"]["threshold"] = threshold; save_data(data)
    embed = discord.Embed(title="✅ 門檻已更新", description=f"業績解鎖門檻設為 **${threshold:,.0f}**", color=GREEN)
    await interaction.response.send_message(embed=embed)

@tree.command(name="管理員_設定兼職預設時薪", description="【管理員】設定兼職全域預設時薪")
@app_commands.describe(hourly="時薪（元）")
@is_admin()
async def admin_set_part_hourly(interaction: discord.Interaction, hourly: float):
    data = load_data(); data["config"]["part_hourly"] = hourly; save_data(data)
    embed = discord.Embed(title="✅ 兼職預設時薪已更新", description=f"兼職預設時薪設為 **${hourly}/hr**", color=GREEN)
    await interaction.response.send_message(embed=embed)

@tree.command(name="管理員_查看員工", description="【管理員】查看指定員工資訊")
@app_commands.describe(member="員工")
@is_admin()
async def admin_view_emp(interaction: discord.Interaction, member: discord.Member):
    data = load_data(); uid = str(member.id); emp = get_emp(data, uid); cfg = data["config"]
    recs = emp["records"]; total_mins = sum(r["total_mins"] for r in recs); perf = total_perf(emp)
    salary_info = f"月薪 ${emp.get('monthly_salary') or '未設定'}" if emp["type"] == "full" else f"時薪 ${get_part_rate(emp, cfg)}/hr {'🔓個人' if emp.get('custom_hourly') else '預設'}"
    embed = discord.Embed(title=f"👤 {member.display_name} 員工資訊", color=PURPLE)
    embed.add_field(name="類型",     value="👔 正職" if emp["type"] == "full" else "🕐 兼職", inline=True)
    embed.add_field(name="薪資設定", value=salary_info, inline=True)
    embed.add_field(name="目前狀態", value="🟢 上班中" if emp["punched_in"] else "⚫ 下班中", inline=True)
    embed.add_field(name="出勤筆數", value=f"{len(recs)} 筆", inline=True)
    embed.add_field(name="累積工時", value=fmt_hm(total_mins), inline=True)
    embed.add_field(name="累積業績", value=f"${perf:,.0f}", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="管理員_月報表", description="【管理員】查看所有員工當月薪資報表")
@app_commands.describe(month="月份 格式 2025/05，留空為本月")
@is_admin()
async def admin_monthly_report(interaction: discord.Interaction, month: str = None):
    data = load_data(); cfg = data["config"]; now = now_tw()
    target = month if month else now.strftime("%Y/%m")
    try: y, m = int(target[:4]), int(target[5:7])
    except:
        await interaction.response.send_message("❌ 月份格式錯誤，請用 2025/05", ephemeral=True); return
    work_days = working_days_in_month(y, m)
    full_lines = []; part_lines = []; full_total = 0; part_total = 0
    for uid, emp in data["employees"].items():
        recs = [r for r in emp["records"] if r["date"].startswith(target)]
        if not recs: continue
        days = len(recs); total_mins = sum(r["total_mins"] for r in recs)
        name = emp.get("name") or f"UID:{uid[:6]}"
        if emp["type"] == "full":
            monthly = emp.get("monthly_salary")
            if not monthly: full_lines.append(f"`{name}` {days}天 ⚠️ 未設月薪"); continue
            gross = round((monthly / work_days) * days)
            _, _, _, net = calc_deductions(gross, cfg); full_total += net
            full_lines.append(f"`{name}` {days}天 → **${net:,}**（月薪 ${monthly:,}）")
        else:
            hourly = get_part_rate(emp, cfg); gross = round((total_mins / 60) * hourly)
            _, _, _, net = calc_deductions(gross, cfg); part_total += net
            rate_tag = "🔓" if emp.get("custom_hourly") else ""
            part_lines.append(f"`{name}` {rate_tag} {days}天 {fmt_hm(total_mins)} → **${net:,}**")
    if not full_lines and not part_lines:
        await interaction.response.send_message(f"📭 {target} 無任何出勤紀錄", ephemeral=True); return
    embed = discord.Embed(title=f"📊 {target} 月薪報表", color=PURPLE)
    embed.add_field(name="當月工作日", value=f"{work_days} 天", inline=False)
    if full_lines: embed.add_field(name="👔 正職員工", value="\n".join(full_lines), inline=False)
    if part_lines: embed.add_field(name="🕐 兼職員工", value="\n".join(part_lines), inline=False)
    grand = full_total + part_total
    embed.add_field(name="薪資支出總計", value=f"正職：${full_total:,}　兼職：${part_total:,}　**合計：${grand:,}**", inline=False)
    embed.set_footer(text="🔓 = 業績達標個人時薪　金額均為實領（已扣勞健保）")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ 此指令需要管理員權限", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 發生錯誤：{error}", ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ 請設定環境變數 DISCORD_TOKEN"); exit(1)
    bot.run(TOKEN)
