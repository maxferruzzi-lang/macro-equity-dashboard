import os
from datetime import datetime
import pandas as pd
import requests
from fredapi import Fred

FRED_API_KEY = os.environ.get("FRED_API_KEY")

START_DATE = "2022-01-01"
FRED_FETCH_START = (pd.Timestamp(START_DATE) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
END_DATE = datetime.today().strftime("%Y-%m-%d")

FRED_SERIES = {
    "US_CPI": "CPIAUCSL",
    "US_UNEMPLOYMENT": "UNRATE",
    "US_GDP": "GDP",
    "US_2S10S_SPREAD": "T10Y2Y",
}

EQUITY_TICKERS = {
    "SP500": "^GSPC",
    "FTSE100": "^FTSE",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def fetch_fred_data(api_key: str, series_dict: dict, start: str, end: str) -> pd.DataFrame:
    if not api_key:
        raise ValueError(
            "No FRED API key found. Set FRED_API_KEY as an environment "
            "variable before running this script."
        )

    fred = Fred(api_key=api_key)
    series_frames = []

    for name, series_id in series_dict.items():
        print(f"Fetching FRED series: {name} ({series_id})...")
        data = fred.get_series(series_id, observation_start=start, observation_end=end)
        series_frames.append(data.rename(name))

    combined = pd.concat(series_frames, axis=1)
    combined.index.name = "date"
    return combined


ONS_SERIES = {
    "UK_CPI": {
        "topic": "economy/inflationandpriceindices",
        "dataset": "mm23",
        "timeseries": "d7g7",
    },
    "UK_UNEMPLOYMENT": {
        "topic": "employmentandlabourmarket/peoplenotinwork/unemployment",
        "dataset": "lms",
        "timeseries": "mgsx",
    },
    "UK_GDP": {
        "topic": "economy/grossdomesticproductgdp",
        "dataset": "qna",
        "timeseries": "ihyq",
    },
}

ONS_BASE_URL = "https://www.ons.gov.uk/{topic}/timeseries/{timeseries}/{dataset}/data"

def fetch_ons_series(name: str, topic: str, dataset: str, timeseries: str) -> pd.DataFrame:
    url = ONS_BASE_URL.format(topic=topic, timeseries=timeseries, dataset=dataset)
    print(f"Fetching ONS series: {name}...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()

    block_key = "quarters" if name == "UK_GDP" else "months"
    observations = payload.get(block_key, [])

    records = []
    for obs in observations:
        date = _parse_ons_date(obs["date"], quarterly=(block_key == "quarters"))
        records.append({"date": date, name: float(obs["value"])})

    return pd.DataFrame(records)

def _parse_ons_date(raw_date: str, quarterly: bool) -> pd.Timestamp:
    if quarterly:
        year, quarter = raw_date.split(" ")
        month = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}[quarter]
        return pd.Timestamp(year=int(year), month=month, day=1)
    else:
        return pd.to_datetime(raw_date, format="%Y %b")

def fetch_ons_data(series_dict: dict) -> pd.DataFrame:
    frames = [
        fetch_ons_series(name, cfg["topic"], cfg["dataset"], cfg["timeseries"]).set_index("date")
        for name, cfg in series_dict.items()
    ]
    combined = pd.concat(frames, axis=1)
    combined.index.name = "date"
    return combined


def fetch_equity_data(tickers: dict, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    frames = []
    for name, ticker in tickers.items():
        print(f"Fetching equity data: {name} ({ticker})...")
        data = yf.download(ticker, start=start, end=end, progress=False)
        close = data["Close"]

        # Newer yfinance versions return Close as a 1-column DataFrame
        # even for a single ticker, rather than a plain Series.
        # If that's happened, pull out that single column as a Series.
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        frames.append(close.rename(name))

    combined = pd.concat(frames, axis=1)
    combined.index.name = "date"
    return combined

def clean_macro_data(df: pd.DataFrame, start: str = None, end: str = None, growth_columns: dict = None) -> pd.DataFrame:
    monthly = df.resample("MS").mean()
    last_real_date = {col: monthly[col].last_valid_index() for col in monthly.columns}

    monthly = monthly.ffill()
    monthly = monthly.dropna(how="all")

    if growth_columns:
        for col, periods in growth_columns.items():
            monthly[col] = monthly[col].pct_change(periods=periods) * 100
            cutoff = last_real_date[col]
            if cutoff is not None:
                monthly.loc[monthly.index > cutoff, col] = pd.NA

    if start:
        monthly = monthly[monthly.index >= start]
    if end:
        monthly = monthly[monthly.index <= end]

    return monthly

def clean_equity_data(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.ffill()
    cleaned = cleaned.dropna(how="all")
    return cleaned


def export_to_csv(df: pd.DataFrame, filename: str, output_dir: str = DATA_DIR) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    df.to_csv(path)
    print(f"Saved {filename} ({len(df)} rows) to {output_dir}")

def main():
    print("=== Macro & Equity Dashboard: Data Pipeline ===\n")

    us_macro_raw = fetch_fred_data(FRED_API_KEY, FRED_SERIES, FRED_FETCH_START, END_DATE)
    us_macro_clean = clean_macro_data(us_macro_raw, START_DATE, END_DATE, growth_columns={"US_CPI": 12, "US_GDP": 3})
    export_to_csv(us_macro_clean, "us_macro.csv")

    uk_macro_raw = fetch_ons_data(ONS_SERIES)
    uk_macro_clean = clean_macro_data(uk_macro_raw, START_DATE, END_DATE)
    export_to_csv(uk_macro_clean, "uk_macro.csv")

    equity_raw = fetch_equity_data(EQUITY_TICKERS, START_DATE, END_DATE)
    equity_clean = clean_equity_data(equity_raw)
    export_to_csv(equity_clean, "equity_data.csv")

    print("\nPipeline complete. CSVs are in the data/ folder, ready for Phase 2.")


if __name__ == "__main__":
    main()
    
