"""Waeyuk mandatory chain layer — forces GPT through agents/skills on every write.

Bundle mirrored from MAIN server (ss-root):
  /opt/jisr-mcp/waeyuk_bundle/{agent,skills,command,AGENTS.md,opencode.jsonc}

Policy:
  - READ tools (ss_readfile, ss_search, ss_db, waeyuk_agents_list, ...) stay OPEN.
  - WRITE tools (ss_writefile, jisr_agent, jisr_bg, ss_exec-write) REQUIRE a live chain_id.
  - One user order => one chain of 10 mandatory stages => long, multi-angle session.
  - Each stage maps to a real agent/skill file from the bundle (no invention).
"""

import json
import os
import re
import time
from pathlib import Path

BUNDLE = Path("/opt/jisr-mcp/waeyuk_bundle")
CHAIN_DB = Path("/var/lib/jisr-chains.json")
if not CHAIN_DB.parent.exists():
    CHAIN_DB = Path("/tmp/jisr-chains.json")

# stage: (key, title, skill_dir_or_agent, agent_md, what_to_do)
STAGES = [
    ("SPEC", "1/10 SPEC — spec-architect",
     "waeyuk-agent-spec-architect", "spec-architect.md",
     "اقرأ سكيل waeyuk-agent-spec-architect ونفذه: Executive Summary + Business Goal + User Stories + FR-XXX + NFR + Acceptance Criteria + Test Plan + Rollback + Definition of Done. ممنوع أي كود قبل Spec معتمد."),
    ("CLARIFY", "2/10 CLARIFY — speckit.clarify",
     "waeyuk-command-speckit.clarify", "spec-architect.md",
     "شغل أسئلة التوضيح المنظمة على الغامض، وثق الافتراضات القابلة للعكس في 2.9، وكمل بدون انتظار (ما عدا irreversible stakes)."),
    ("PLAN", "3/10 PLAN — architect",
     "waeyuk-agent-architect", "architect.md",
     "اقرأ سكيل architect: ادرس الكود القائم (brownfield أولا)، ثم plan.md + بنية + ADRs. أي قرار معماري يتسجل decisions/ADR-*.md."),
    ("TASKS", "4/10 TASKS — speckit.tasks",
     "waeyuk-command-speckit.tasks", "spec-architect.md",
     "قسم plan.md لمهام صغيرة قابلة للتنفيذ tasks.md بترتيب صحيح وكل واحدة ليها Acceptance."),
    ("BUILD", "5/10 BUILD — implementer/backend/frontend",
     "waeyuk-agent-implementer", "implementer.md",
     "نفذ phase-by-phase عبر jisr_agent/ss_writefile (مع chain_id). التزم بالبنية والـ conventions. designer للـ UI، legal-egypt لو needs_lawyer (قرار WL-* بدون لمس كود)."),
    ("TEST", "6/10 TEST — tester",
     "waeyuk-agent-tester", "tester.md",
     "شغل unit+integration+E2E. لا مرحلة تكتمل بدون اختبارات ناجحة. أي حساب اختبار يتحذف نهائيا بعد الانتهاء (قرار المالك 2026-09-09)."),
    ("SECURITY", "7/10 SECURITY+DATA — security/database",
     "waeyuk-agent-security", "security.md",
     "راجع OWASP + صلاحيات + pentest خفيف، ثم database skill: schema/queries/سلامة/أداء. ممنوع تغيير بيانات مستخدم حقيقي بدون إذن صريح (قرار 2026-09-11)."),
    ("QUALITY", "8/10 QUALITY — clean-code/performance/bug-hunt",
     "waeyuk-agent-clean-code", "clean-code.md",
     "عدي على clean-code ثم performance (اختناقات/cache) ثم bug-hunt (تتبع source-to-sink). الفرق بين must-fix وshould-fix."),
    ("REVIEW", "9/10 REVIEW — critic + vision",
     "waeyuk-agent-critic", "critic.md",
     "استدع critic لمراجعة مخرجات اتنين agents وكشف التناقضات، و vision تلقائيا لأي صورة أو UI-QA (لقطة ديسكتوب+موبايل + PASS/FAIL)."),
    ("DELIVER", "10/10 DELIVER — changelog",
     "waeyuk-agent-orchestrator", "orchestrator.md",
     "علّم Spec بـ Status: Completed + Changelog، ونضف حسابات التيست، وتقرير نهائي واحد بالإنجليزية (عربي لو اتطلب)."),
]

WRITE_PAT = re.compile(
    r"(>|tee\b|sed\s+-i|awk\s+-i|rm\s|mv\s|cp\s|mkdir\s|touch\s|chmod\s|chown\s|"
    r"docker\s+exec[^|]*\b(mysql|psql|sh|bash)\b[^|]*(INSERT|UPDATE|DELETE|DROP|CREATE)|"
    r"mysql[^|]*(INSERT|UPDATE|DELETE|DROP)|apt(-get)?\s+(install|remove)|"
    r"systemctl\s+(restart|stop|start)|reboot|shutdown|base64\s+-d\s*>\s*\S|"
    r"cat\s*>\s*\S|printf[^|]*>\s*\S)",
    re.I)


def _load():
    try:
        return json.loads(CHAIN_DB.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        CHAIN_DB.parent.mkdir(parents=True, exist_ok=True)
        CHAIN_DB.write_text(json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def _get(cid):
    d = _load()
    c = d.get((cid or "").strip())
    if not c:
        return None, d
    if time.time() - c.get("updated", 0) > 6 * 3600:
        return None, d
    return c, d


def chain_required(chain_id=""):
    """Return (True,'') if chain live, else (False, refuse_msg)."""
    c, _ = _get(chain_id)
    if c:
        return True, ""
    return False, (
        "REFUSED — no live chain. الكتابة على السيرفر الكبير اجباري عبر السلسلة.\n"
        "1) waeyuk_start(task=\"...\") لفتح chain جديد (هيرجع chain_id + مرحلة SPEC).\n"
        "2) نفذ كل مرحلة بالترتيب عبر waeyuk_advance(chain_id, stage_output).\n"
        "3) أدوات الكتابة (ss_writefile / jisr_agent / jisr_bg / ss_exec-write) تاخد chain_id معاها.\n"
        "القراءة (ss_readfile/ss_search/ss_db) مفتوحة بدون chain للاستكشاف."
    )


def touch_chain(chain_id):
    try:
        d = _load()
        c = d.get(chain_id)
        if c:
            c["updated"] = time.time()
            d[chain_id] = c
            _save(d)
    except Exception:
        pass


def is_write_command(cmd):
    c = cmd or ""
    if not c.strip():
        return False
    # read-only allowlist
    if re.match(r"(?is)^\s*(uptime|free\b|df\b|ls\b|cat\s+\S+|head\b|tail\b|"
                r"docker\s+ps\b|docker\s+logs\b|git\s+(status|diff|log)\b|"
                r"pwd|whoami|id\b|hostname|date|echo\s+[^\|>\;]*)\s*$", c.strip()):
        # pure single read command (no chaining) -> read
        if not re.search(r"[;&|]{1,2}\s*\w", c):
            return False
    return bool(WRITE_PAT.search(c))


def _skill_head(skill_dir, max_chars=2500):
    try:
        p = BUNDLE / "skills" / skill_dir / "SKILL.md"
        t = p.read_text(encoding="utf-8", errors="ignore")
        return t[:max_chars]
    except Exception as e:
        return "(skill not found: %s %s)" % (skill_dir, e)


def _stage_msg(chain_id, idx):
    key, title, skill, agent_md, do = STAGES[idx]
    head = _skill_head(skill)
    return (
        "CHAIN %s | %s\n"
        "TASK: %s\n"
        "SKILL (bundle/skills/%s/SKILL.md مقتطف):\n%s\n\n"
        "AGENT (bundle/agent/%s): اقرأه كاملا عبر waeyuk_skill_read قبل التنفيذ.\n"
        "المطلوب في المرحلة دي:\n%s\n\n"
        "خلص المرحلة ثم نادي: waeyuk_advance(chain_id=\"%s\", stage_output=\"<ناتج المرحلة>\")\n"
        "ممنوع القفز لمرحلة تالية. chain_id إجباري في ss_writefile/jisr_agent/jisr_bg/ss_exec."
        % (chain_id, title, _load().get(chain_id, {}).get("task", ""),
           skill, head, agent_md, do, chain_id)
    )


def register_chain_tools(mcp):
    @mcp.tool()
    def waeyuk_agents_list() -> str:
        """List ALL agents/skills/commands mirrored from the MAIN server (no chain needed). ابدأ بيها قبل أي شغل."""
        out = ["== agents (bundle/agent) =="]
        try:
            ad = BUNDLE / "agent"
            out += sorted(p.name for p in ad.iterdir()
                          if p.is_file() and p.suffix == ".md"
                          and ".bak-" not in p.name)
        except Exception as e:
            out.append("agent list error: %s" % e)
        out.append("== skills (bundle/skills) ==")
        try:
            sd = BUNDLE / "skills"
            out += sorted(p.name for p in sd.iterdir() if p.is_dir())
        except Exception as e:
            out.append("skills list error: %s" % e)
        out.append("== commands (bundle/command) ==")
        try:
            cd = BUNDLE / "command"
            out += sorted(p.name for p in cd.iterdir() if p.is_file())
        except Exception as e:
            out.append("commands list error: %s" % e)
        out.append("== chain ==")
        out.append("10 مراحل إجبارية: SPEC>CLARIFY>PLAN>TASKS>BUILD>TEST>SECURITY>QUALITY>REVIEW>DELIVER. "
                   "افتح chain عبر waeyuk_start ثم تقدم عبر waeyuk_advance.")
        return "\n".join(out)

    @mcp.tool()
    def waeyuk_skill_read(name: str) -> str:
        """Read one agent/skill/command file from the bundle (no chain needed). name مثل: waeyuk-agent-orchestrator أو spec-architect.md أو speckit.plan.md"""
        n = (name or "").strip()
        if not n or len(n) > 120 or re.search(r"\.\.|/", n):
            # allow skill/subdir form like waeyuk-agent-x/SKILL.md? keep simple
            if "/" in n:
                p = (BUNDLE / "skills" / n)
                try:
                    rp = p.resolve()
                    if BUNDLE not in rp.parents:
                        return "REFUSED: outside bundle."
                    return rp.read_text(encoding="utf-8", errors="ignore")[:20000] or "(empty)"
                except Exception as e:
                    return "NOT FOUND: %s" % e
            return "Bad name. مثال: waeyuk-agent-orchestrator | spec-architect.md | speckit.plan.md"
        cands = [
            BUNDLE / "skills" / n / "SKILL.md",
            BUNDLE / "agent" / (n if n.endswith(".md") else n + ".md"),
            BUNDLE / "command" / (n if n.endswith(".md") else n + ".md"),
        ]
        for p in cands:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="ignore")[:30000] or "(empty)"
        return "NOT FOUND: %s (جرّب waeyuk_agents_list)" % n

    @mcp.tool()
    def waeyuk_start(task: str) -> str:
        """OPEN a mandatory work chain for one user order. يرجع chain_id + المرحلة 1/10. أي كتابة بعد كده لازم تحمل chain_id."""
        t = (task or "").strip()
        if len(t) < 10:
            return "Give a specific task (min 10 chars) — الأمر لازم يكون واضح عشان السلسلة تغطيه من كل الزوايا."
        if len(t) > 4000:
            return "Task too long (max 4000 chars)."
        import secrets as _sx
        cid = "w" + time.strftime("%Y%m%d-%H%M%S") + "-" + _sx.token_hex(3)
        d = _load()
        d[cid] = {"task": t, "stage": 0, "done": [], "created": time.time(),
                  "updated": time.time()}
        # prune old
        for k in [k for k, v in d.items()
                  if time.time() - v.get("updated", 0) > 6 * 3600]:
            d.pop(k, None)
        _save(d)
        return ("CHAIN OPENED: %s\n"
                "القاعدة: أمر واحد = 10 مراحل إجبارية بالترتيب، كل مرحلة تستخدم الـ agent/skill بتاعها من الباندل. "
                "ممنوع الاختصار وممنوع الكتابة بدون chain_id.\n\n" % cid
                + _stage_msg(cid, 0))

    @mcp.tool()
    def waeyuk_advance(chain_id: str, stage_output: str) -> str:
        """Submit current stage output, validate, move to NEXT stage. يناديها GPT بعد كل مرحلة (10 مرات على الأقل للأمر الواحد)."""
        c, d = _get(chain_id)
        if not c:
            return ("BAD chain_id. افتح واحد جديد عبر waeyuk_start(task=\"...\"). "
                    + chain_required("")[1])
        out = (stage_output or "").strip()
        if len(out) < 20:
            return ("REFUSED: ناتج المرحلة قصير جدا (min 20 chars). "
                    "نفذ المرحلة %s بجد عبر السكيل بتاعها ثم أعد المحاولة."
                    % STAGES[c["stage"]][1])
        idx = c["stage"]
        c["done"].append({"stage": STAGES[idx][0], "len": len(out),
                          "at": time.time()})
        if idx >= len(STAGES) - 1:
            c["stage"] = len(STAGES)  # finished
            c["updated"] = time.time()
            d[chain_id] = c
            _save(d)
            return ("CHAIN DONE %s — الـ 10 مراحل خلصت: SPEC>CLARIFY>PLAN>TASKS>BUILD>TEST>SECURITY>QUALITY>REVIEW>DELIVER.\n"
                    "اتأكد: Spec=Completed+Changelog، حسابات التيست محذوفة، بيانات المستخدمين الحقيقيين لم تمس بدون إذن."
                    % chain_id)
        c["stage"] = idx + 1
        c["updated"] = time.time()
        d[chain_id] = c
        _save(d)
        return _stage_msg(chain_id, idx + 1)

    @mcp.tool()
    def waeyuk_chain_status(chain_id: str) -> str:
        """Show chain progress: task, current stage, done stages."""
        c, _ = _get(chain_id)
        if not c:
            return "NO SUCH CHAIN (expired after 6h?). افتح جديد عبر waeyuk_start."
        names = [STAGES[i][0] for i in range(c["stage"])]
        return ("CHAIN %s\nTASK: %s\nSTAGE: %d/10 (%s)\nDONE: %s"
                % (chain_id, c["task"], c["stage"] + 1,
                   STAGES[min(c["stage"], 9)][0],
                   ", ".join(s["stage"] for s in c["done"]) or "-"))

    @mcp.tool()
    def waeyuk_task(task: str, chain_id: str = "") -> str:
        """MANDATORY GATEWAY for any real work on the MAIN server. لو مفيش chain_id بيفتح chain جديد ويرجع خطة السلسلة الكاملة (لازم تمشي عليها). لو فيه chain_id بيرجع تعليمات المرحلة الحالية بالسكيل بتاعها."""
        if not (chain_id or "").strip():
            t = (task or "").strip()
            if len(t) < 10:
                return ("كل شغل حقيقي يبدأ من هنا. اديني task واضح (min 10 chars) "
                        "أو افتح chain عبر waeyuk_start ثم استخدم chain_id في كل أدوات الكتابة.")
            import secrets as _sx
            cid = "w" + time.strftime("%Y%m%d-%H%M%S") + "-" + _sx.token_hex(3)
            d = _load()
            d[cid] = {"task": t, "stage": 0, "done": [], "created": time.time(),
                      "updated": time.time()}
            _save(d)
            stages = "\n".join("%d. %s (skill: %s / agent: %s)" % (
                i + 1, s[0], s[2], s[3]) for i, s in enumerate(STAGES))
            return ("GATEWAY CHAIN %s OPENED.\nTASK: %s\n\n"
                    "خطة السلسلة الإجبارية (10 مراحل — ممنوع تخطي أي واحدة):\n%s\n\n"
                    "القواعد: كل مرحلة تقرأ سكيلها عبر waeyuk_skill_read، تنفذها، ثم waeyuk_advance. "
                    "الكتابة (ss_writefile/jisr_agent/jisr_bg/ss_exec-write) لازم تحمل chain_id=\"%s\".\n\n"
                    % (cid, t, stages, cid) + _stage_msg(cid, 0))
        c, _ = _get(chain_id)
        if not c:
            return chain_required(chain_id)[1]
        touch_chain(chain_id)
        return _stage_msg(chain_id, min(c["stage"], 9))
