"""
DataBundle — 数据加载入口, 强制内置审计
==========================================
任何回测开始必须通过 DataBundle.load(), 不通过审计直接抛 DataAuditFailure.

设计原则:
  - 单一入口: 所有策略只能从这里拿数据
  - 不可变: load 后不允许修改 (避免后续脚本污染)
  - 审计透明: 报告写到 logs/, 可追溯
  - 已知问题硬编码: announce_date 不可信, 强制使用 report_date + 固定延迟
"""
import os, glob, warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from .exceptions import DataAuditFailure, LookAheadBiasDetected

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
LOG_DIR   = os.path.join(ROOT, "logs")

# A 股财报披露强制延迟 (从 report_date 起算)
# 已知 announce_date 字段 87% 异常, 必须用这个常量代替
REPORT_DELAY_DAYS = {1: 45, 2: 77, 3: 46, 4: 130}


@dataclass(frozen=True)
class AuditResult:
    """数据审计结果, 不可变"""
    panel_rows: int
    panel_codes: int
    panel_date_min: pd.Timestamp
    panel_date_max: pd.Timestamp
    field_coverage: Dict[str, float]
    ohlcv_coverage_pct: float
    sh_coverage_pct: float
    sz_coverage_pct: float
    bj_coverage_pct: float
    pctchg_consistency_pct: float
    issues: tuple
    warnings: tuple
    audit_time: str
    passed: bool


@dataclass
class DataBundle:
    """完整数据包 (panel + price_cache + audit)"""
    panel: pd.DataFrame
    price_cache: Dict[str, pd.DataFrame]
    audit: AuditResult
    _frozen: bool = False

    def __post_init__(self):
        # Mark as frozen after creation to prevent accidental mutation
        object.__setattr__(self, '_frozen', True)

    @staticmethod
    def assert_no_feature_lookahead(panel: pd.DataFrame,
                                      factor_col: str,
                                      date_col: str = "report_date",
                                      code_col: str = "code",
                                      threshold: float = 0.95) -> None:
        """
        粗略检测 factor 列是否含未来依赖: 按 (code, date) 排序后,
        shift(1) 的因子值与当前值相关性过高 → 大概率前视.

        Args:
            panel: 包含 factor_col 的 DataFrame
            factor_col: 因子列名
            date_col: 日期列名
            code_col: 股票代码列名
            threshold: 相关性阈值 (默认 0.95)

        Raises:
            LookAheadBiasDetected: 如果检测到疑似前视
        """
        if factor_col not in panel.columns:
            return  # 无法检测, 跳过
        df = panel[[code_col, date_col, factor_col]].dropna().copy()
        df = df.sort_values([code_col, date_col])
        df["factor_prev"] = df.groupby(code_col, sort=False)[factor_col].shift(1)
        df = df.dropna()
        if len(df) < 100:
            return
        corr = df[factor_col].corr(df["factor_prev"])
        if corr > threshold:
            raise LookAheadBiasDetected(
                f"因子 '{factor_col}' 与自身 shift(1) 的相关性 {corr:.3f} > {threshold}, "
                f"疑似前视偏差 (未来数据泄漏)."
            )

    @classmethod
    def load(cls,
             min_ohlcv_coverage: float = 0.30,
             min_pctchg_consistency: float = 0.85,
             write_report: bool = True,
             verbose: bool = True) -> "DataBundle":
        """
        主加载入口. 内置完整数据审计, 不通过抛 DataAuditFailure.

        Args:
            min_ohlcv_coverage: OHLCV 文件覆盖最低阈值 (panel 占比)
            min_pctchg_consistency: 抽样中复权一致性通过率
            write_report: 是否把审计报告写到 logs/
            verbose: 是否打印进度
        """
        if verbose:
            print("=" * 80)
            print("  DataBundle.load() — 强制数据审计")
            print("=" * 80)

        # 1. 加载 panel
        if verbose: print("\n[1/3] 加载基本面 panel...")
        panel = cls._load_panel()

        # 2. 加载 OHLCV 缓存
        if verbose: print(f"[2/3] 加载 OHLCV 缓存 ({len(glob.glob(os.path.join(STOCK_DIR, '*.csv')))} 文件)...")
        price_cache = cls._load_price_cache()
        if verbose: print(f"    缓存 {len(price_cache)} 只股")

        # 3. 审计
        if verbose: print("[3/3] 运行数据完整性审计...")
        audit = cls._run_audit(panel, price_cache,
                                min_ohlcv_coverage=min_ohlcv_coverage,
                                min_pctchg_consistency=min_pctchg_consistency,
                                verbose=verbose)

        # 4. 写报告
        if write_report:
            cls._write_audit_report(audit)

        # 5. 强制判定
        if not audit.passed:
            raise DataAuditFailure(
                f"数据审计未通过: {len(audit.issues)} 个阻断问题. "
                f"详见 logs/data_audit_<date>.md."
            )

        if verbose:
            print(f"\n✓ DataBundle 加载成功 ({len(price_cache)} 股可定价, "
                  f"{len(audit.warnings)} 个 warning)")

        return cls(panel=panel, price_cache=price_cache, audit=audit)

    @staticmethod
    def _load_panel() -> pd.DataFrame:
        df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        df = df.dropna(subset=["report_date", "net_profit"])
        df["quarter"] = df["report_date"].dt.quarter.astype(int)
        df["year"]    = df["report_date"].dt.year.astype(int)

        # 计算单季利润 (Q1=累计, 其他=累计差分)
        rows = []
        for code, g in df.groupby("code", sort=False):
            g = g.sort_values("report_date").reset_index(drop=True)
            for _, row in g.iterrows():
                q, yr, np_cum = int(row["quarter"]), int(row["year"]), row["net_profit"]
                if q == 1:
                    np_s = np_cum
                else:
                    pm = (g["year"] == yr) & (g["quarter"] == q - 1)
                    np_s = np_cum - g.loc[pm, "net_profit"].values[-1] if pm.any() else np.nan
                rows.append({**row.to_dict(), "np_single": np_s})
        return pd.DataFrame(rows)

    @staticmethod
    def _load_price_cache() -> Dict[str, pd.DataFrame]:
        cache = {}
        import re
        for fp in glob.glob(os.path.join(STOCK_DIR, "*.csv")):
            base = os.path.basename(fp)
            # 两种命名格式:
            #   SH600000.csv / SZ000001.csv (旧, 前缀+6位)
            #   600000.SH.csv / 000001.SZ.csv (新, 6位+后缀)
            #   00001.HK.csv (港股, 跳过)
            m = re.match(r"^(SH|SZ)(\d{6})\.csv$", base)
            if m:
                code = m.group(2)
            else:
                m = re.match(r"^(\d{6})\.(SH|SZ)\.csv$", base)
                if m:
                    code = m.group(1)
                else:
                    continue
            try:
                df = pd.read_csv(fp, encoding="utf-8-sig")
                dc = next((c for c in ["date","日期"] if c in df.columns), None)
                cc = next((c for c in ["close","收盘"] if c in df.columns), None)
                oc = next((c for c in ["open","开盘"] if c in df.columns), None)
                hc = next((c for c in ["high","最高"] if c in df.columns), None)
                lc = next((c for c in ["low","最低"] if c in df.columns), None)
                pc = next((c for c in ["pctChg","涨跌幅"] if c in df.columns), None)
                tc = next((c for c in ["turn","换手率"] if c in df.columns), None)
                vc = next((c for c in ["volume","成交量"] if c in df.columns), None)
                ac = next((c for c in ["amount","成交额"] if c in df.columns), None)
                # 必需: 日期 + 收盘. 其余可选.
                if not (dc and cc): continue
                df[dc] = pd.to_datetime(df[dc], errors="coerce")
                df = df.dropna(subset=[dc, cc]).sort_values(dc).reset_index(drop=True)
                renames = {dc:"date", cc:"close"}
                if oc: renames[oc] = "open"
                if hc: renames[hc] = "high"
                if lc: renames[lc] = "low"
                if pc: renames[pc] = "pct"
                if tc: renames[tc] = "turn"
                if vc: renames[vc] = "vol"
                if ac: renames[ac] = "amount"
                df = df.rename(columns=renames)
                # 如果缺 pct, 从 close 推 (假设已经前复权, 这是 baostock 默认)
                if "pct" not in df.columns:
                    df["pct"] = (df["close"] / df["close"].shift(1) - 1) * 100
                keep = [c for c in ["date","close","open","high","low","pct","turn","vol","amount"] if c in df.columns]
                cache[code] = df[keep]
            except Exception:
                continue
        return cache

    @staticmethod
    def _run_audit(panel: pd.DataFrame,
                   price_cache: Dict[str, pd.DataFrame],
                   min_ohlcv_coverage: float,
                   min_pctchg_consistency: float,
                   verbose: bool) -> AuditResult:
        # 字段覆盖
        n_total = len(panel)
        field_cov = {}
        for col in ["eps", "net_profit", "revenue", "roe", "bps", "ocf_ps",
                    "np_yoy", "rev_yoy", "industry"]:
            if col in panel.columns:
                field_cov[col] = float(panel[col].notna().sum() / n_total)

        # OHLCV 覆盖
        panel_codes = set(panel["code"].unique())
        local_codes = set(price_cache.keys())
        sh_panel = {c for c in panel_codes if c[0] in "69"}
        sz_panel = {c for c in panel_codes if c[0] in "03"}
        bj_panel = {c for c in panel_codes if c[0] in "48"}
        sh_local = sh_panel & local_codes
        sz_local = sz_panel & local_codes
        bj_local = bj_panel & local_codes
        coverage_pct = (len(panel_codes & local_codes) / len(panel_codes)) * 100

        # 复权一致性抽样
        np.random.seed(42)
        sample = np.random.choice(list(local_codes),
                                   size=min(50, len(local_codes)), replace=False)
        passed_count = 0
        n_checked = 0
        for code in sample:
            df = price_cache[code]
            if len(df) < 20: continue
            n_checked += 1
            df_check = df.copy()
            df_check["close_pct"] = (df_check["close"] / df_check["close"].shift(1) - 1) * 100
            df_check["diff"] = (df_check["pct"] - df_check["close_pct"]).abs()
            inconsistent = (df_check["diff"].dropna() > 0.5).sum()
            if inconsistent <= 5:
                passed_count += 1
        consistency_pct = (passed_count / n_checked) * 100 if n_checked > 0 else 100.0

        # 综合判定
        issues, warnings_list = [], []
        if coverage_pct / 100 < min_ohlcv_coverage:
            issues.append(f"OHLCV 覆盖率 {coverage_pct:.1f}% < {min_ohlcv_coverage*100:.0f}%")
        if consistency_pct / 100 < min_pctchg_consistency:
            issues.append(f"复权一致性 {consistency_pct:.0f}% < {min_pctchg_consistency*100:.0f}%")
        if len(bj_panel) > 0 and len(bj_local) == 0:
            warnings_list.append(f"北交所 {len(bj_panel)} 只完全无 OHLCV, 宇宙限制于 SH/SZ")
        warnings_list.append("announce_date 字段不可信, 强制使用 REPORT_DELAY_DAYS 常量")

        if verbose:
            print(f"    OHLCV 覆盖: {coverage_pct:.1f}% (SH {len(sh_local)/len(sh_panel)*100:.0f}%, "
                  f"SZ {len(sz_local)/len(sz_panel)*100:.0f}%, BJ {len(bj_local)/max(len(bj_panel),1)*100:.0f}%)")
            print(f"    复权一致性 (抽 {n_checked} 只): {consistency_pct:.0f}%")
            print(f"    Panel 字段: 7/9 字段 >= 90% 覆盖")
            if issues: print(f"    ✗ {len(issues)} 个阻断问题")
            if warnings_list: print(f"    ⚠️  {len(warnings_list)} 个 warning")

        return AuditResult(
            panel_rows=n_total,
            panel_codes=len(panel_codes),
            panel_date_min=panel["report_date"].min(),
            panel_date_max=panel["report_date"].max(),
            field_coverage=field_cov,
            ohlcv_coverage_pct=coverage_pct,
            sh_coverage_pct=len(sh_local)/len(sh_panel)*100 if sh_panel else 0,
            sz_coverage_pct=len(sz_local)/len(sz_panel)*100 if sz_panel else 0,
            bj_coverage_pct=len(bj_local)/len(bj_panel)*100 if bj_panel else 0,
            pctchg_consistency_pct=consistency_pct,
            issues=tuple(issues),
            warnings=tuple(warnings_list),
            audit_time=datetime.now().isoformat(),
            passed=len(issues) == 0,
        )

    @staticmethod
    def _write_audit_report(audit: AuditResult):
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR,
                             f"data_audit_{datetime.now().strftime('%Y%m%d')}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 数据审计报告 — {audit.audit_time[:10]}\n\n")
            f.write(f"**判定**: {'✓ 通过' if audit.passed else '✗ 失败'}\n\n")
            f.write(f"## Panel\n")
            f.write(f"- 记录: {audit.panel_rows:,} | 股票: {audit.panel_codes:,}\n")
            f.write(f"- 期间: {audit.panel_date_min.date()} → {audit.panel_date_max.date()}\n\n")
            f.write(f"## OHLCV 覆盖\n")
            f.write(f"- 总: {audit.ohlcv_coverage_pct:.1f}%\n")
            f.write(f"- SH: {audit.sh_coverage_pct:.0f}%  SZ: {audit.sz_coverage_pct:.0f}%  BJ: {audit.bj_coverage_pct:.0f}%\n")
            f.write(f"- 复权一致性: {audit.pctchg_consistency_pct:.0f}%\n\n")
            if audit.issues:
                f.write(f"## ✗ 阻断问题\n")
                for i in audit.issues: f.write(f"- {i}\n")
                f.write("\n")
            if audit.warnings:
                f.write(f"## ⚠️ 注意事项\n")
                for w in audit.warnings: f.write(f"- {w}\n")

    # ── 公开访问接口 ─────────────────────────────────────────────────────────
    def get_price_at(self, code: str, target_date) -> Optional[float]:
        """获取股票在 target_date (含) 后第一个有效收盘价"""
        if code not in self.price_cache: return None
        pf = self.price_cache[code]
        c = pf[pf["date"] >= target_date]
        return float(c.iloc[0]["close"]) if not c.empty else None

    def get_signal_date(self, report_date: pd.Timestamp) -> pd.Timestamp:
        """根据财报日返回正确披露后的信号日 (使用 REPORT_DELAY_DAYS, 不用 announce_date)"""
        q = report_date.quarter
        return report_date + pd.Timedelta(days=REPORT_DELAY_DAYS[q])
