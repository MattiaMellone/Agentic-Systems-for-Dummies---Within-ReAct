"""Tools module.
Provides functions: _require_env, _openai_client, _timezone, _now_iso_date_local, _parse_date_with_llm, date_math, tavily_search, openmeteo_forecast, openmeteo_archive.

This code is organized for readability, maintainability, and testability."""

from __future__ import annotations
import os
import re
import time
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def _require_env(var: str) -> str:
    """Require env.

Args:
    var: Input parameter.
Returns:
    Return value."""
    val = os.getenv(var, '').strip()
    if not val:
        raise RuntimeError(f'Missing environment variable: {var}')
    return val


def _openai_client() -> 'OpenAI':
    """Openai client.

Returns:
    Return value."""
    if OpenAI is None:
        raise RuntimeError('OpenAI SDK not available. Install `openai`>=1.0.')
    return OpenAI()


def _timezone() -> ZoneInfo:
    """Timezone.

Returns:
    Return value."""
    tz_name = os.getenv('TIMEZONE', 'Europe/Rome').strip() or 'Europe/Rome'
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo('Europe/Rome')


def _now_iso_date_local() -> str:
    """Now iso date local.

Returns:
    Return value."""
    tz = _timezone()
    now = datetime.now(tz)
    return now.strftime('%Y-%m-%d')


def _parse_date_with_llm(text: str, today_iso: Optional[str] = None) -> str:
    """Parse date with llm.

Args:
    text: Input parameter.
    today_iso: Input parameter.
Returns:
    Return value."""
    client = _openai_client()
    if today_iso is None:
        today_iso = _now_iso_date_local()
    system = f"You are a date normalization assistant.\nYou must resolve the user-provided date expression into an absolute calendar date in ISO 8601 format (YYYY-MM-DD).\nToday's reference date is: {today_iso}.\nIf the input cannot be understood, respond with the single token: ERROR."
    user = f'Input: {text}\nReturn only the ISO date, nothing else.'
    resp = client.chat.completions.create(model='gpt-4o-mini', temperature=0.0,
                                          messages=[{'role': 'system', 'content': system},
                                                    {'role': 'user', 'content': user}])
    out = (resp.choices[0].message.content or '').strip()
    if out.upper().startswith('ERROR') or not re.match('^\\d{4}-\\d{2}-\\d{2}$', out):
        raise ValueError(f'LLM could not parse date from: {text!r}')
    return out


def date_math(operation: str, date: Optional[str] = None, days: Optional[int] = None, end_date: Optional[str] = None) -> \
Dict[str, Any]:
    """Date math.

Args:
    operation: Input parameter.
    date: Input parameter.
    days: Input parameter.
    end_date: Input parameter.
Returns:
    Return value."""
    op = (operation or '').strip().lower()
    if op not in {'add', 'sub', 'diff', 'range'}:
        raise ValueError('operation must be one of: add, sub, diff, range')
    today_iso = _now_iso_date_local()

    def _to_tuple(d: str) -> (int, int, int):
        """To tuple.

Args:
    d: Input parameter.
Returns:
    Return value."""
        y, m, dd = d.split('-')
        return (int(y), int(m), int(dd))

    def _to_epoch_days(d: str) -> int:
        """To epoch days.

Args:
    d: Input parameter.
Returns:
    Return value."""
        y, m, dd = _to_tuple(d)
        return int(time.mktime((y, m, dd, 12, 0, 0, 0, 0, -1)) // 86400)

    def _from_epoch_days(ed: int) -> str:
        """From epoch days.

Args:
    ed: Input parameter.
Returns:
    Return value."""
        return datetime.utcfromtimestamp(ed * 86400).strftime('%Y-%m-%d')

    if op in {'add', 'sub'}:
        if date is None or days is None:
            raise ValueError("add/sub require 'date' and 'days'")
        base_iso = _parse_date_with_llm(date, today_iso)
        delta = int(days)
        if op == 'sub':
            delta = -delta
        base_ed = _to_epoch_days(base_iso)
        res_iso = _from_epoch_days(base_ed + delta)
        return {'operation': op, 'base': base_iso, 'days': int(days), 'result': res_iso}
    if date is None or end_date is None:
        raise ValueError("diff/range require 'date' (start) and 'end_date' (end)")
    start_iso = _parse_date_with_llm(date, today_iso)
    end_iso = _parse_date_with_llm(end_date, today_iso)
    start_ed, end_ed = (_to_epoch_days(start_iso), _to_epoch_days(end_iso))
    diff_days = end_ed - start_ed
    if op == 'diff':
        return {'operation': 'diff', 'start': start_iso, 'end': end_iso, 'days': diff_days}
    else:
        return {'operation': 'range', 'start': start_iso, 'end': end_iso, 'days_inclusive': diff_days + 1}


def tavily_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Tavily search.

Args:
    query: Input parameter.
    max_results: Input parameter.
Returns:
    Return value."""
    api_key = _require_env('TAVILY_API_KEY')
    max_results = max(1, min(10, int(max_results)))
    url = 'https://api.tavily.com/search'
    payload = {'api_key': api_key, 'query': query, 'max_results': max_results, 'search_depth': 'advanced',
               'include_answer': False, 'include_images': False, 'include_domains': None, 'exclude_domains': None,
               'include_raw_content': False}
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f'Tavily API error: HTTP {resp.status_code} - {resp.text}')
    data = resp.json()
    results = []
    for item in data.get('results', []):
        results.append({'title': item.get('title'), 'url': item.get('url'), 'content': item.get('content'),
                        'score': item.get('score')})
    return {'query': query, 'results': results}


def openmeteo_forecast(location: str, units: str = 'metric', days: int = 1, target_date: Optional[str] = None) -> Dict[
    str, Any]:
    """Openmeteo forecast.

Args:
    location: Input parameter.
    units: Input parameter.
    days: Input parameter.
    target_date: Input parameter.
Returns:
    Return value."""
    if days < 1:
        days = 1
    if days > 16:
        raise ValueError(
            'Requested forecast horizon exceeds provider limits (max 16 days). Please request 16 days or fewer.')
    u = (units or 'metric').lower()
    if u not in {'metric', 'imperial'}:
        u = 'metric'
    temp_unit = 'celsius' if u == 'metric' else 'fahrenheit'
    wind_unit = 'kmh' if u == 'metric' else 'mph'
    precip_unit = 'mm' if u == 'metric' else 'inch'
    today_iso = _now_iso_date_local()

    def _to_epoch_days_iso(s: str) -> int:
        """To epoch days iso.

Args:
    s: Input parameter.
Returns:
    Return value."""
        y, m, d = map(int, s.split('-'))
        return int(time.mktime((y, m, d, 12, 0, 0, 0, 0, -1)) // 86400)

    start_ed = _to_epoch_days_iso(today_iso)
    max_ed = start_ed + 16
    tgt_iso: Optional[str] = None
    if target_date and target_date.strip():
        td = target_date.strip()
        if re.match('^\\d{4}-\\d{2}-\\d{2}$', td):
            tgt_iso = td
        else:
            tgt_iso = _parse_date_with_llm(td, today_iso)
        tgt_ed = _to_epoch_days_iso(tgt_iso)
        if tgt_ed < start_ed or tgt_ed > max_ed:
            raise ValueError(
                f"Requested date {tgt_iso} is outside the forecast window ({today_iso} .. {datetime.utcfromtimestamp(max_ed * 86400).strftime('%Y-%m-%d')}). Pass a relative phrase like 'domani' or 'dopodomani', or choose a date within 16 days.")
    geo_url = 'https://geocoding-api.open-meteo.com/v1/search'
    g = requests.get(geo_url, params={'name': location, 'count': 1, 'language': 'en', 'format': 'json'}, timeout=20)
    if g.status_code != 200:
        raise RuntimeError(f'Open-Meteo geocoding error: HTTP {g.status_code} - {g.text}')
    geo = g.json()
    results = geo.get('results') or []
    if not results:
        raise ValueError(f'Location not found: {location!r}')
    city = results[0]
    lat, lon = (city['latitude'], city['longitude'])
    name = city.get('name') or location
    country = city.get('country')
    fc_url = 'https://api.open-meteo.com/v1/forecast'
    daily_vars = ['temperature_2m_max', 'temperature_2m_min', 'precipitation_sum', 'precipitation_probability_max',
                  'windspeed_10m_max', 'weathercode', 'sunrise', 'sunset']
    params = {'latitude': lat, 'longitude': lon, 'timezone': 'auto', 'daily': ','.join(daily_vars),
              'temperature_unit': temp_unit, 'windspeed_unit': wind_unit, 'precipitation_unit': precip_unit}
    if tgt_iso:
        params['start_date'] = tgt_iso
        params['end_date'] = tgt_iso
    else:
        params['forecast_days'] = int(days)
    r = requests.get(fc_url, params=params, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f'Open-Meteo forecast error: HTTP {r.status_code} - {r.text} | params={params}')
    data = r.json()
    daily = data.get('daily') or {}
    dates = daily.get('time') or []
    tmax = daily.get('temperature_2m_max') or []
    tmin = daily.get('temperature_2m_min') or []
    psum = daily.get('precipitation_sum') or []
    pprob = daily.get('precipitation_probability_max') or []
    wmax = daily.get('windspeed_10m_max') or []
    wcode = daily.get('weathercode') or []
    sunrise = daily.get('sunrise') or []
    sunset = daily.get('sunset') or []
    daily_norm: List[Dict[str, Any]] = []
    for i in range(len(dates)):
        daily_norm.append({'date': dates[i], 'temp_min': tmin[i] if i < len(tmin) else None,
                           'temp_max': tmax[i] if i < len(tmax) else None,
                           'precip_sum': psum[i] if i < len(psum) else None,
                           'precip_prob_max': pprob[i] if i < len(pprob) else None,
                           'windspeed_max': wmax[i] if i < len(wmax) else None,
                           'weathercode': wcode[i] if i < len(wcode) else None,
                           'sunrise': sunrise[i] if i < len(sunrise) else None,
                           'sunset': sunset[i] if i < len(sunset) else None})
    if tgt_iso and len(daily_norm) != 1:
        raise RuntimeError(
            f'Provider did not return a single-day forecast for {tgt_iso}. It may be out of forecast range (max 16 days).')
    return {'location': {'name': name, 'country': country, 'lat': lat, 'lon': lon}, 'units': u, 'daily': daily_norm,
            'provider_note': 'Daily forecast limited to 16 days by Open-Meteo.'}


def openmeteo_archive(location: str, start_date: str, end_date: str, units: str = 'metric') -> Dict[str, Any]:
    """Openmeteo archive.

Args:
    location: Input parameter.
    start_date: Input parameter.
    end_date: Input parameter.
    units: Input parameter.
Returns:
    Return value."""
    today_iso = _now_iso_date_local()
    start_iso = _parse_date_with_llm(start_date, today_iso)
    end_iso = _parse_date_with_llm(end_date, today_iso)
    if start_iso > end_iso:
        raise ValueError(f'start_date {start_iso} must be <= end_date {end_iso}')

    def _to_epoch_days_iso(s: str) -> int:
        """To epoch days iso.

Args:
    s: Input parameter.
Returns:
    Return value."""
        y, m, d = map(int, s.split('-'))
        return int(time.mktime((y, m, d, 12, 0, 0, 0, 0, -1)) // 86400)

    span = _to_epoch_days_iso(end_iso) - _to_epoch_days_iso(start_iso) + 1
    if span > 31:
        raise ValueError(f'Date range too large ({span} days). Please request 31 days or fewer.')
    u = (units or 'metric').lower()
    if u not in {'metric', 'imperial'}:
        u = 'metric'
    temp_unit = 'celsius' if u == 'metric' else 'fahrenheit'
    wind_unit = 'kmh' if u == 'metric' else 'mph'
    precip_unit = 'mm' if u == 'metric' else 'inch'
    geo_url = 'https://geocoding-api.open-meteo.com/v1/search'
    g = requests.get(geo_url, params={'name': location, 'count': 1, 'language': 'en', 'format': 'json'}, timeout=20)
    if g.status_code != 200:
        raise RuntimeError(f'Open-Meteo geocoding error: HTTP {g.status_code} - {g.text}')
    geo = g.json()
    results = geo.get('results') or []
    if not results:
        raise ValueError(f'Location not found: {location!r}')
    city = results[0]
    lat, lon = (city['latitude'], city['longitude'])
    name = city.get('name') or location
    country = city.get('country')
    arch_url = 'https://archive-api.open-meteo.com/v1/era5'
    daily_vars = ['temperature_2m_max', 'temperature_2m_min', 'precipitation_sum', 'windspeed_10m_max', 'weathercode']
    params = {'latitude': lat, 'longitude': lon, 'start_date': start_iso, 'end_date': end_iso,
              'daily': ','.join(daily_vars), 'timezone': 'auto', 'temperature_unit': temp_unit,
              'windspeed_unit': wind_unit, 'precipitation_unit': precip_unit}
    r = requests.get(arch_url, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f'Open-Meteo ERA5 error: HTTP {r.status_code} - {r.text}')
    data = r.json()
    daily = data.get('daily') or {}
    dates = daily.get('time') or []
    tmax = daily.get('temperature_2m_max') or []
    tmin = daily.get('temperature_2m_min') or []
    psum = daily.get('precipitation_sum') or []
    wmax = daily.get('windspeed_10m_max') or []
    wcode = daily.get('weathercode') or []
    if not dates:
        raise RuntimeError('Provider returned no daily records for the requested range.')
    daily_norm: List[Dict[str, Any]] = []
    n = len(dates)
    for i in range(n):
        daily_norm.append({'date': dates[i], 'temp_min': tmin[i] if i < len(tmin) else None,
                           'temp_max': tmax[i] if i < len(tmax) else None,
                           'precip_sum': psum[i] if i < len(psum) else None,
                           'windspeed_max': wmax[i] if i < len(wmax) else None,
                           'weathercode': wcode[i] if i < len(wcode) else None})
    return {'location': {'name': name, 'country': country, 'lat': lat, 'lon': lon}, 'units': u, 'start_date': start_iso,
            'end_date': end_iso, 'daily': daily_norm, 'provider_note': 'Historical daily data from ERA5 reanalysis.'}
