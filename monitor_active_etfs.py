from abc import ABC, abstractmethod
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os
import time
import sys

# Ensure output directory exists
OUTPUT_DIR = "etf_data"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

class ETFScraper(ABC):
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7'
        }

    @abstractmethod
    def fetch_holdings(self, etf_code):
        pass

    def save_debug_html(self, etf_code, html_content):
        filename = f"{OUTPUT_DIR}/debug_{etf_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[DEBUG] Saved HTML to {filename}")

class UnifiedScraper(ETFScraper):
    def fetch_holdings(self, etf_code):
        # Target URL for Unified ETF (EZMoney)
        # Note: ETF code '00981A' maps to internal ID '49YTW'
        # Found via manual browser navigation
        url_map = {
            '00981A': 'https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW'
        }
        
        url = url_map.get(etf_code)
        if not url:
            print(f"No known URL for {etf_code}. Please update url_map.")
            return None

        print(f"Fetching {url}... (This may take a moment)")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data for {etf_code}: {e}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Heuristic: Find table with '股票名稱' and '比例' headers
        # Unified site structure might change, so we search for keywords.
        tables = soup.find_all('table')
        target_table = None
        for table in tables:
            text = table.get_text()
            # Keywords often found in holdings tables
            if '股票名稱' in text and ('比例' in text or '權重' in text or '股數' in text):
                target_table = table
                break
        
        if not soup.find('div', id='DataAsset'):
            print(f"Could not find DataAsset div for {etf_code}. Dumping HTML for debugging...")
            self.save_debug_html(etf_code, response.text)
            return None
            
        try:
            import json
            import html
            
            data_div = soup.find('div', id='DataAsset')
            json_str = html.unescape(data_div['data-content'])
            data = json.loads(json_str)
            
            # Find the stock assets
            holdings = []
            for item in data:
                if item.get('AssetCode') == 'ST' and 'Details' in item:
                    for detail in item['Details']:
                        holdings.append({
                            'stock_id': detail.get('DetailCode', '').strip(),
                            'stock_name': detail.get('DetailName', '').strip(),
                            'shares': float(detail.get('Share', 0)),
                            'weight': float(detail.get('NavRate', 0)),
                            'amount': float(detail.get('Amount', 0))
                        })
            
            if not holdings:
                print(f"No stock holdings found in JSON data for {etf_code}")
                return None
                
            return pd.DataFrame(holdings)
            
        except Exception as e:
            print(f"Error parsing JSON data for {etf_code}: {e}")
            self.save_debug_html(etf_code, response.text)
            return None

def enrich_with_previous(curr_df, prev_df=None):
    """
    Add comparison columns to the current holdings DataFrame:
      - is_new        : True if the stock was not in the previous day's holdings
      - amount_change : change in position value (NTD) vs previous day (reflects both trades and price moves)
      - shares_change : change in share count vs previous day (positive = bought, negative = sold)
      - weight_change : change in portfolio weight (%) vs previous day
    All change columns are 0 when prev_df is None (first run) or when the stock is new.
    """
    curr = curr_df.copy()
    if prev_df is None:
        curr['is_new'] = True
        curr['amount_change'] = 0.0
        curr['shares_change'] = 0.0
        curr['weight_change'] = 0.0
    else:
        # Only use the core price/share columns from prev to avoid picking up stale enrichment cols
        prev = prev_df[['stock_id', 'amount', 'shares', 'weight']].rename(columns={
            'amount': 'prev_amount',
            'shares': 'prev_shares',
            'weight': 'prev_weight',
        })
        merged = curr.merge(prev, on='stock_id', how='left')
        curr['is_new']        = merged['prev_amount'].isna()
        curr['amount_change'] = (merged['amount'] - merged['prev_amount'].fillna(0)).round(0)
        curr['shares_change'] = (merged['shares'] - merged['prev_shares'].fillna(0)).round(0)
        curr['weight_change'] = (merged['weight'] - merged['prev_weight'].fillna(0)).round(4)
    return curr


def monitor_etfs():
    print("Starting Active ETF Monitor...")
    print(f"Output directory: {os.path.abspath(OUTPUT_DIR)}")

    # Active ETFs List
    # Users can add more here
    target_etfs = [
        {'code': '00981A', 'scraper': UnifiedScraper()},
        # Placeholder for other scrapers
        # {'code': '00980A', 'scraper': NomuraScraper()},
    ]

    all_data = []

    for etf in target_etfs:
        scraper = etf['scraper']
        print(f"Processing {etf['code']}...")
        df = scraper.fetch_holdings(etf['code'])
        if df is not None and not df.empty:
            all_data.append(df)
            print(f"Successfully fetched {len(df)} constituents for {etf['code']}")
            print(df.head())
        else:
            print(f"Failed to fetch data for {etf['code']}")

    if all_data:
        final_df = pd.concat(all_data)

        timestamp = datetime.now().strftime("%Y%m%d")
        filename = os.path.join(OUTPUT_DIR, f'etf_holdings_{timestamp}.csv')

        # Find previous CSV for enrichment
        existing_files = sorted([
            f for f in os.listdir(OUTPUT_DIR)
            if f.startswith('etf_holdings_') and f.endswith('.csv')
        ])
        if existing_files:
            prev_file = os.path.join(OUTPUT_DIR, existing_files[-1])
            df_prev = pd.read_csv(prev_file, encoding='utf-8-sig')
            final_df = enrich_with_previous(final_df, df_prev)
            print(f"[INFO] Enriched with previous day data from {existing_files[-1]}")
        else:
            final_df = enrich_with_previous(final_df, None)
            print("[INFO] No previous data found; marking all positions as new.")

        final_df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n[SUCCESS] Saved enriched data to: {filename}")

        # Comparison Logic
        try:
            files = sorted([
                f for f in os.listdir(OUTPUT_DIR)
                if f.startswith('etf_holdings_') and f.endswith('.csv')
            ])
            if len(files) >= 2:
                prev_file = os.path.join(OUTPUT_DIR, files[-2])
                curr_file = os.path.join(OUTPUT_DIR, files[-1])
                print(f"[INFO] Comparing {curr_file} with {prev_file}...")
                df_curr = pd.read_csv(curr_file, encoding='utf-8-sig')
                df_prev = pd.read_csv(prev_file, encoding='utf-8-sig')
                diff_data = compare_holdings(df_curr, df_prev)
                generate_html_report(diff_data, timestamp)
            else:
                print("[INFO] Not enough history for comparison (need at least 2 days).")
        except Exception as e:
            print(f"[ERROR] Comparison failed: {e}")
            import traceback
            traceback.print_exc()

        return final_df
    else:
        print("\n[WARNING] No data fetched from any source.")
    return None

def compare_holdings(df_curr, df_prev):
    """
    Compare current and previous holdings.
    Returns a dictionary of changes per ETF with keys: 'new', 'exit', 'changed'.
    """
    changes = {}

    if 'ETF' not in df_curr.columns: df_curr['ETF'] = '00981A'
    if 'ETF' not in df_prev.columns: df_prev['ETF'] = '00981A'

    etfs = df_curr['ETF'].unique()

    for etf in etfs:
        curr_etf = df_curr[df_curr['ETF'] == etf].set_index('stock_id')
        prev_etf = df_prev[df_prev['ETF'] == etf].set_index('stock_id')

        # New Positions
        new_stocks = curr_etf.index.difference(prev_etf.index)
        new_df = curr_etf.loc[new_stocks].copy()

        # Exited Positions
        exited_stocks = prev_etf.index.difference(curr_etf.index)
        exit_df = prev_etf.loc[exited_stocks].copy()

        # Changed Positions
        common_stocks = curr_etf.index.intersection(prev_etf.index)
        curr_common = curr_etf.loc[common_stocks]
        prev_common = prev_etf.loc[common_stocks]

        weight_diff  = curr_common['weight'] - prev_common['weight']
        shares_diff  = curr_common['shares'] - prev_common['shares']
        amount_diff  = curr_common['amount'] - prev_common['amount']

        changed_mask = (weight_diff.abs() > 0.001) | (shares_diff.abs() > 0)

        changed_df = pd.DataFrame({
            'stock_name':   curr_common.loc[changed_mask, 'stock_name'],
            'shares_prev':  prev_common.loc[changed_mask, 'shares'],
            'shares_curr':  curr_common.loc[changed_mask, 'shares'],
            'shares_diff':  shares_diff[changed_mask],
            'amount_prev':  prev_common.loc[changed_mask, 'amount'],
            'amount_curr':  curr_common.loc[changed_mask, 'amount'],
            'amount_diff':  amount_diff[changed_mask],
            'weight_prev':  prev_common.loc[changed_mask, 'weight'],
            'weight_curr':  curr_common.loc[changed_mask, 'weight'],
            'weight_diff':  weight_diff[changed_mask],
        })

        changes[etf] = {
            'new':     new_df,
            'exit':    exit_df,
            'changed': changed_df.sort_values(by='amount_diff', ascending=False),
        }

    return changes

def _fmt_amount(val):
    """Format NTD amount in 億/萬 for readability."""
    try:
        v = float(val)
    except (ValueError, TypeError):
        return str(val)
    if abs(v) >= 1e8:
        return f"{v/1e8:+.2f} 億"
    if abs(v) >= 1e4:
        return f"{v/1e4:+.2f} 萬"
    return f"{v:+.0f}"


def generate_html_report(diff_data, date_str):
    """Generate HTML report with new/exited/changed sections and per-stock flow amounts."""
    css = """
        body { font-family: Arial, sans-serif; margin: 20px; color: #333; }
        h1 { color: #222; }
        h2 { color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px; }
        h3 { margin-top: 20px; color: #444; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 14px; }
        th, td { border: 1px solid #ddd; padding: 7px 10px; text-align: left; }
        th { background: #f2f2f2; }
        tr:nth-child(even) { background: #fafafa; }
        .num  { text-align: right; }
        .up   { color: #16a34a; font-weight: bold; }
        .dn   { color: #dc2626; font-weight: bold; }
        .new-badge  { background: #2563eb; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 12px; }
        .exit-badge { background: #9ca3af; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 12px; }
        .etf-section { margin-bottom: 48px; border: 1px solid #ccc; padding: 20px; border-radius: 6px; }
        .summary { display: flex; gap: 24px; margin-bottom: 16px; }
        .summary-card { border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px 20px; min-width: 120px; text-align: center; }
        .summary-card .val { font-size: 28px; font-weight: bold; }
        .summary-card .lbl { font-size: 12px; color: #666; }
    """

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Active ETF Daily Changes - {date_str}</title>
  <style>{css}</style>
</head>
<body>
  <h1>Active ETF Holdings — Daily Change Report ({date_str})</h1>
"""

    for etf, data in diff_data.items():
        n_new    = len(data['new'])
        n_exit   = len(data['exit'])
        n_change = len(data['changed'])

        html_content += f"""
  <div class='etf-section'>
    <h2>ETF：{etf}</h2>
    <div class='summary'>
      <div class='summary-card'><div class='val up'>{n_new}</div><div class='lbl'>新增持倉</div></div>
      <div class='summary-card'><div class='val dn'>{n_exit}</div><div class='lbl'>移出持倉</div></div>
      <div class='summary-card'><div class='val'>{n_change}</div><div class='lbl'>持倉變動</div></div>
    </div>
"""

        # --- New Positions ---
        html_content += "<h3>🆕 新增持倉</h3>"
        if not data['new'].empty:
            html_content += """<table><thead><tr>
              <th>股票代碼</th><th>名稱</th><th>股數</th><th>持倉金額 (NTD)</th><th>權重 %</th>
            </tr></thead><tbody>"""
            for sid, row in data['new'].iterrows():
                html_content += f"""<tr>
                  <td>{sid} <span class='new-badge'>NEW</span></td>
                  <td>{row['stock_name']}</td>
                  <td class='num'>{int(row['shares']):,}</td>
                  <td class='num'>{int(row['amount']):,}</td>
                  <td class='num'>{row['weight']}%</td>
                </tr>"""
            html_content += "</tbody></table>"
        else:
            html_content += "<p>無新增持倉。</p>"

        # --- Exited Positions ---
        html_content += "<h3>🚪 移出持倉</h3>"
        if not data['exit'].empty:
            html_content += """<table><thead><tr>
              <th>股票代碼</th><th>名稱</th><th>前日股數</th><th>前日持倉金額 (NTD)</th><th>前日權重 %</th>
            </tr></thead><tbody>"""
            for sid, row in data['exit'].iterrows():
                html_content += f"""<tr>
                  <td>{sid} <span class='exit-badge'>OUT</span></td>
                  <td>{row['stock_name']}</td>
                  <td class='num'>{int(row['shares']):,}</td>
                  <td class='num'>{int(row['amount']):,}</td>
                  <td class='num'>{row['weight']}%</td>
                </tr>"""
            html_content += "</tbody></table>"
        else:
            html_content += "<p>無移出持倉。</p>"

        # --- Changed Positions ---
        html_content += "<h3>📊 持倉變動（含每日進出金額）</h3>"
        if not data['changed'].empty:
            html_content += """<table><thead><tr>
              <th>股票代碼</th><th>名稱</th>
              <th>股數 (前)</th><th>股數 (今)</th><th>股數變動</th>
              <th>進出金額 (NTD)</th>
              <th>權重 (前)</th><th>權重 (今)</th><th>權重變動</th>
            </tr></thead><tbody>"""
            for sid, row in data['changed'].iterrows():
                s_diff = row['shares_diff']
                s_cls  = "up" if s_diff > 0 else ("dn" if s_diff < 0 else "")

                a_diff = row['amount_diff']
                a_cls  = "up" if a_diff > 0 else ("dn" if a_diff < 0 else "")
                a_str  = _fmt_amount(a_diff)

                w_diff = row['weight_diff']
                w_cls  = "up" if w_diff > 0 else ("dn" if w_diff < 0 else "")

                html_content += f"""<tr>
                  <td>{sid}</td>
                  <td>{row['stock_name']}</td>
                  <td class='num'>{int(row['shares_prev']):,}</td>
                  <td class='num'>{int(row['shares_curr']):,}</td>
                  <td class='num {s_cls}'>{int(s_diff):+,}</td>
                  <td class='num {a_cls}'>{a_str}</td>
                  <td class='num'>{row['weight_prev']}%</td>
                  <td class='num'>{row['weight_curr']}%</td>
                  <td class='num {w_cls}'>{w_diff:+.2f}%</td>
                </tr>"""
            html_content += "</tbody></table>"
        else:
            html_content += "<p>無顯著持倉變動。</p>"

        html_content += "  </div>\n"

    html_content += "</body>\n</html>\n"

    report_file = os.path.join(OUTPUT_DIR, f"report_{date_str}.html")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"\n[REPORT] Generated HTML report: {report_file}")

    generate_index_page(date_str)

    try:
        if os.name == 'nt':
            os.startfile(report_file)
    except:
        pass

def generate_index_page(latest_date):
    """
    Generate index.html: links to the latest comparison report
    and embeds the enriched holdings table (with is_new / amount_change).
    """
    import glob as _glob

    # Load latest enriched CSV
    csv_files = sorted(_glob.glob(os.path.join(OUTPUT_DIR, 'etf_holdings_*.csv')))
    holdings_rows = ""
    if csv_files:
        import csv as _csv
        with open(csv_files[-1], encoding='utf-8-sig') as f:
            reader = _csv.DictReader(f)
            for r in reader:
                is_new      = str(r.get('is_new', 'False')).lower() == 'true'
                amt_change  = float(r.get('amount_change', 0) or 0)
                shr_change  = float(r.get('shares_change', 0) or 0)
                wgt_change  = float(r.get('weight_change', 0) or 0)

                new_badge   = "<span class='new-badge'>NEW</span>" if is_new else ""
                a_cls = "up" if amt_change > 0 else ("dn" if amt_change < 0 else "")
                a_str = _fmt_amount(amt_change) if not is_new else "—"
                s_cls = "up" if shr_change > 0 else ("dn" if shr_change < 0 else "")
                s_str = f"{int(shr_change):+,}" if not is_new else "—"
                w_cls = "up" if wgt_change > 0 else ("dn" if wgt_change < 0 else "")
                w_str = f"{wgt_change:+.2f}%" if not is_new else "—"

                holdings_rows += f"""<tr>
                  <td>{r['stock_id']} {new_badge}</td>
                  <td>{r['stock_name']}</td>
                  <td class='num'>{int(float(r['shares'])):,}</td>
                  <td class='num'>{r['weight']}%</td>
                  <td class='num'>{int(float(r['amount'])):,}</td>
                  <td class='num {s_cls}'>{s_str}</td>
                  <td class='num {a_cls}'>{a_str}</td>
                  <td class='num {w_cls}'>{w_str}</td>
                </tr>\n"""

    # Links to past comparison reports
    report_files = sorted(_glob.glob(os.path.join(OUTPUT_DIR, 'report_*.html')), reverse=True)
    report_links = "".join(
        f'<li><a href="{rf}">報告 {os.path.basename(rf)}</a></li>'
        for rf in report_files[:10]
    ) or "<li>（累積兩天資料後自動產生）</li>"

    latest_report_link = (
        f'<a href="{report_files[0]}">查看最新比較報告 →</a>'
        if report_files else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Active ETF Monitor</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 40px auto; padding: 0 20px; color: #333; }}
    h1 {{ border-bottom: 2px solid #eee; padding-bottom: 10px; }}
    h2 {{ color: #555; margin-top: 30px; }}
    .meta {{ color: #666; margin: 8px 0 20px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 8px; }}
    th, td {{ border: 1px solid #ddd; padding: 7px 10px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    .num  {{ text-align: right; }}
    .up   {{ color: #16a34a; font-weight: bold; }}
    .dn   {{ color: #dc2626; font-weight: bold; }}
    .new-badge {{ background: #2563eb; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 11px; }}
    ul {{ line-height: 1.9; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <h1>📊 Active ETF Monitor</h1>
  <p class="meta">最後更新：<strong>{datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</strong>
  &nbsp;&nbsp;{latest_report_link}</p>

  <h2>目前持股（{os.path.basename(csv_files[-1]) if csv_files else '—'}）</h2>
  <table>
    <thead><tr>
      <th>股票代碼</th><th>名稱</th><th>股數</th><th>權重 %</th><th>持倉金額 (NTD)</th>
      <th>股數變動</th><th>進出金額</th><th>權重變動</th>
    </tr></thead>
    <tbody>{holdings_rows}</tbody>
  </table>

  <h2>歷史比較報告</h2>
  <ul>{report_links}</ul>
</body>
</html>
"""

    with open("index.html", 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"[INFO] Updated index.html (latest report: {latest_date})")

if __name__ == "__main__":
    try:
        monitor_etfs()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...") # Keep window open if double clicked
