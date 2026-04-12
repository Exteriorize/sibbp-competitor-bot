from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://sibbp.ru/"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}
CATEGORY_FALLBACKS = {
    "Офис": "https://sibbp.ru/index.php?path=59&route=product/category",
    "Склад": "https://sibbp.ru/index.php?path=60&route=product/category",
    "Универсальное": "https://sibbp.ru/index.php?path=63&route=product/category",
}
TITLE_KEYWORDS = (
    "офис",
    "склад",
    "помещ",
    "площад",
    "производственно-склад",
    "универсаль",
)
ADDRESS_HINTS = (
    "богаткова",
    "б. богаткова",
    "бориса богаткова",
    "толстого",
    "выборной",
    "толмачев",
    "сухарн",
)
EXCLUDED_TITLE_PARTS = (
    "выбор помещений",
    "аренда помещений",
    "фильтр",
    "показано с",
    "сибирский бизнес парк",
    "заказать",
    "контакты",
    "выгоды сотрудничества",
    "отзывы",
    "оставить заявку",
)
PRODUCT_DETAIL_SELECTORS = (
    "h1",
    "h2",
    ".product-info",
    ".product-layout",
    ".product-thumb",
    ".description",
    "#tab-description",
    ".tab-content",
    "#content",
    ".content",
)
FILTERPRO_URL = urljoin(BASE_URL, "index.php?route=module/filterpro/getproduct")
FILTERPRO_HEADERS = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": BASE_URL,
}

# Актуальные фолбэки именно под текущий каталог SibBP.
# Нужны как страховка, если сайт не отдает product_id рядом с карточкой или
# filterpro возвращает данные не к той карточке. Живые данные сайта выше по приоритету,
# но эти значения исправляют явные несостыковки.
KNOWN_FALLBACKS = {
    ("офис", "2657квмкрылонаборисабогаткова99"): {"area": 265.7, "price_value": 800.0},
    ("офис", "офисплощадь102квмкабинетноготипатолстого133"): {"area": 102.0, "price_value": 700.0},
    ("офис", "офисплощадь164квмкабинетноготипатолстого133"): {"area": 164.0, "price_value": 700.0},
    ("офис", "офисплощадькабинетноготипа442квмббогаткова99"): {"area": 44.2, "price_value": 750.0},
    ("офис", "офисноепомещениенаборисабогаткова99201"): {"area": 30.0, "price_value": 750.0},
    ("офис", "офисноепомещениенатолстого133т201"): {"area": 14.0, "price_value": 800.0},
    ("офис", "офисныепомещениянаборисабогаткова99216"): {"area": 14.1, "price_value": 1300.0},
    ("склад", "производственноскладскоепомещениенавыборной201"): {"area": 85.0, "price_value": 390.0},
    ("склад", "складскоепомещениенавыборной201к7"): {"area": 1385.3, "price_value": 390.0},
    ("универсальное", "складскоепомещениенавыборной201к7"): {"area": 1116.0, "price_value": 390.0},
}


class ParserError(RuntimeError):
    pass


_NUMBER_RE = r"(\d[\d\s]{0,20}(?:[.,]\d+)?)"


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def _normalize_title_key(value: str) -> str:
    value = _normalize_spaces(value).lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", value)


EXCLUDED_EXACT_TITLES = {
    _normalize_title_key("Производственно-складское помещение на Выборной 201"),
}


def _safe_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    response = session.get(url, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def _safe_post(session: requests.Session, url: str, **kwargs) -> requests.Response:
    response = session.post(url, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def _extract_category_urls(soup: BeautifulSoup) -> Dict[str, str]:
    found: Dict[str, str] = {}

    for a in soup.find_all("a", href=True):
        text = _normalize_spaces(a.get_text(" ", strip=True)).lower()
        href = urljoin(BASE_URL, a["href"])

        if "офис" in text:
            found.setdefault("Офис", href)
        elif "склад" in text:
            found.setdefault("Склад", href)
        elif "универс" in text:
            found.setdefault("Универсальное", href)

    for room_type, fallback_url in CATEGORY_FALLBACKS.items():
        found.setdefault(room_type, fallback_url)

    return found


def _extract_page_count(soup: BeautifulSoup) -> int:
    text = _normalize_spaces(soup.get_text(" ", strip=True))
    match = re.search(r"страниц\s*:\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return 1


def _build_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url

    parsed = urlparse(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _looks_like_product_title(text: str) -> bool:
    text_norm = _normalize_spaces(text).lower()
    if len(text_norm) < 8:
        return False
    if any(bad in text_norm for bad in EXCLUDED_TITLE_PARTS):
        return False
    if any(keyword in text_norm for keyword in TITLE_KEYWORDS):
        return True
    has_area = bool(re.search(r"\d+(?:[.,]\d+)?\s*(?:кв\.?\s*м|м²|м2)", text_norm))
    has_hint = any(hint in text_norm for hint in ADDRESS_HINTS)
    return has_area and has_hint


def _clean_title(text: str) -> str:
    text = _normalize_spaces(text)
    text = re.sub(r"\s*\|\s*подробнее.*$", "", text, flags=re.IGNORECASE)
    return text.strip(" -—•")


def _title_key(room_type: str, title: str) -> Tuple[str, str]:
    return room_type.lower(), _normalize_title_key(title)


def _to_float(raw: str) -> float:
    return float(_normalize_spaces(raw).replace(" ", "").replace(",", "."))


def _extract_labeled_value(text: str, labels: Iterable[str], max_value: float = 10_000_000_000) -> float:
    text_norm = _normalize_spaces(text)
    label_group = "|".join(re.escape(label) for label in labels)
    patterns = [
        rf"(?:{label_group})\s*[:\-]?\s*{_NUMBER_RE}",
        rf"(?:{label_group})[^\d]{{0,30}}{_NUMBER_RE}\s*(?:₽|руб(?:\.|лей)?|кв\.?\s*м|м²|м2)?",
    ]
    values: List[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text_norm, flags=re.IGNORECASE):
            try:
                value = _to_float(match.group(1))
            except ValueError:
                continue
            if 0 < value <= max_value:
                values.append(round(value, 2))
    return values[0] if values else 0.0


def _extract_area_candidates(text: str) -> List[float]:
    text_norm = _normalize_spaces(text).lower()
    patterns = [
        r"площад(?:ь|и)?[^\d]{0,20}(\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м²|м2)",
        r"(\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м²|м2)",
    ]
    values: List[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text_norm, flags=re.IGNORECASE):
            raw = match.group(1).replace(" ", "").replace(",", ".")
            try:
                value = float(raw)
            except ValueError:
                continue
            if 1 <= value <= 100000:
                values.append(round(value, 2))
    seen: List[float] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _extract_price_candidates(text: str) -> List[float]:
    text_norm = _normalize_spaces(text)
    patterns = [
        r"(?:цена(?:\s*за\s*м2|\s*за\s*м²|\s*за\s*кв\.?\s*м)?|стоимость(?:\s*за\s*м2|\s*за\s*м²)?)"
        r"[^\d]{0,25}(\d[\d\s]{0,20}(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?)\s*(?:/|за)?\s*(?:м2|м²|кв\.?\s*м)?",
        r"(\d[\d\s]{0,20}(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?)\s*/\s*(?:м2|м²|кв\.?\s*м)",
        r"(\d[\d\s]{0,20}(?:[.,]\d+)?)\s*(?:руб(?:\.|лей)?)\s*за\s*(?:м2|м²|кв\.?\s*м)",
    ]
    values: List[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text_norm, flags=re.IGNORECASE):
            raw_value = _normalize_spaces(match.group(1))
            numeric = raw_value.replace(" ", "").replace(",", ".")
            try:
                number = float(numeric)
            except ValueError:
                continue
            if 1 <= number <= 10000000:
                values.append(round(number, 2))
    seen: List[float] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _format_rub(value: float) -> str:
    if value <= 0:
        return "нет"
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽"


def _format_rub_per_m2(value: float) -> str:
    if value <= 0:
        return "нет"
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽/м²"


def _pick_area(room_type: str, title: str, filterpro_text: str, card_text: str, detail_text: str) -> float:
    labeled = _extract_labeled_value(filterpro_text, ["Площадь", "Площадь помещения"], max_value=100_000)
    if labeled > 0:
        return labeled

    labeled = _extract_labeled_value(detail_text, ["Площадь", "Площадь помещения"], max_value=100_000)
    if labeled > 0:
        return labeled

    title_candidates = _extract_area_candidates(title)
    if title_candidates:
        return title_candidates[0]

    combined_candidates = _extract_area_candidates(_normalize_spaces(" ".join([card_text, detail_text, filterpro_text])))
    if combined_candidates:
        if room_type in {"Склад", "Универсальное"}:
            return max(combined_candidates)
        return combined_candidates[0]

    return 0.0


def _pick_price_per_m2(filterpro_text: str, card_text: str, detail_text: str) -> Tuple[str, float]:
    labeled = _extract_labeled_value(filterpro_text, ["Цена за м2", "Цена за м²", "Цена за кв.м", "Цена за кв м"], max_value=10_000_000)
    if labeled > 0:
        return _format_rub_per_m2(labeled), labeled

    labeled = _extract_labeled_value(detail_text, ["Цена за м2", "Цена за м²", "Цена за кв.м", "Цена за кв м"], max_value=10_000_000)
    if labeled > 0:
        return _format_rub_per_m2(labeled), labeled

    for text in (filterpro_text, card_text, detail_text):
        candidates = _extract_price_candidates(text)
        if candidates:
            value = candidates[0]
            return _format_rub_per_m2(value), value
    return "нет", 0.0


def _pick_total_price(area: float, price_value: float, filterpro_text: str, detail_text: str) -> Tuple[str, float]:
    if area > 0 and price_value > 0:
        total = round(area * price_value, 2)
        return _format_rub(total), total

    labeled = _extract_labeled_value(filterpro_text, ["Цена объекта", "Стоимость объекта", "Общая стоимость", "Арендная плата"], max_value=10_000_000_000)
    if labeled > 0:
        return _format_rub(labeled), labeled

    labeled = _extract_labeled_value(detail_text, ["Цена объекта", "Стоимость объекта", "Общая стоимость", "Арендная плата"], max_value=10_000_000_000)
    if labeled > 0:
        return _format_rub(labeled), labeled

    return "нет", 0.0


def _extract_product_id_from_text(text: str) -> str:
    patterns = [
        r'data-product_id\s*=\s*["\']?(\d+)',
        r'product_id\s*=\s*["\']?(\d+)',
        r'product_id=(\d+)',
        r'name=["\']product_id["\'][^>]*value=["\'](\d+)',
        r'value=["\'](\d+)["\'][^>]*name=["\']product_id["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _find_nearest_product_id(node: Tag, source_url: str = "") -> str:
    current: Optional[Tag] = node
    for _ in range(10):
        if current is None or not isinstance(current, Tag):
            break
        pid = _extract_product_id_from_text(str(current))
        if pid:
            return pid
        current = current.parent if isinstance(current.parent, Tag) else None

    if source_url:
        pid = _extract_product_id_from_text(source_url)
        if pid:
            return pid
        try:
            query = parse_qs(urlparse(source_url).query)
            values = query.get("product_id") or query.get("id")
            if values:
                return str(values[0])
        except Exception:
            pass
    return ""


def _extract_page_product_ids(page_html: str) -> List[str]:
    patterns = [
        r'data-product_id\s*=\s*["\']?(\d+)',
        r'name=["\']product_id["\'][^>]*value=["\'](\d+)',
        r'product_id=(\d+)',
    ]
    values: List[str] = []
    seen: Set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, page_html, flags=re.IGNORECASE):
            pid = match.group(1)
            if pid not in seen:
                seen.add(pid)
                values.append(pid)
    return values


def _flatten_json_strings(value) -> List[str]:
    result: List[str] = []
    if isinstance(value, str):
        text = _normalize_spaces(value)
        if text:
            result.append(text)
    elif isinstance(value, dict):
        for inner in value.values():
            result.extend(_flatten_json_strings(inner))
    elif isinstance(value, list):
        for inner in value:
            result.extend(_flatten_json_strings(inner))
    return result


def _fetch_filterpro_text(session: requests.Session, product_id: str, cache: Dict[str, str]) -> str:
    if not product_id:
        return ""
    cache_key = f"filterpro:{product_id}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        response = _safe_post(
            session,
            FILTERPRO_URL,
            headers=FILTERPRO_HEADERS,
            data={"product_id": product_id},
        )
    except Exception:
        cache[cache_key] = ""
        return ""

    text = response.text or ""
    combined = _normalize_spaces(text)

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "json" in content_type or combined.startswith("{") or combined.startswith("["):
        try:
            data = response.json()
            pieces = _flatten_json_strings(data)
            if pieces:
                combined = _normalize_spaces(" ".join(pieces))
        except (ValueError, json.JSONDecodeError):
            pass

    cache[cache_key] = combined
    return combined


def _fetch_detail_text(session: requests.Session, url: str, cache: Dict[str, str]) -> str:
    if not url or url == BASE_URL:
        return ""
    if url in cache:
        return cache[url]

    try:
        html = _safe_get(session, url).text
    except Exception:
        cache[url] = ""
        return ""

    soup = BeautifulSoup(html, "html.parser")
    text_parts: List[str] = []

    for selector in PRODUCT_DETAIL_SELECTORS:
        for node in soup.select(selector):
            text = _normalize_spaces(node.get_text(" ", strip=True))
            if not text or len(text) < 5:
                continue
            text_parts.append(text)

    if not text_parts:
        page_text = _normalize_spaces(soup.get_text(" ", strip=True))
        if page_text:
            text_parts.append(page_text)

    combined = _normalize_spaces(" ".join(text_parts))
    cache[url] = combined
    return combined


def _best_container(node: Tag) -> Tag:
    current: Optional[Tag] = node
    best: Tag = node
    for _ in range(8):
        if current is None or not isinstance(current, Tag):
            break
        text = _normalize_spaces(current.get_text(" ", strip=True))
        href_count = len(current.find_all("a", href=True)) if hasattr(current, "find_all") else 0
        if 5 <= len(text) <= 1200 and href_count <= 20:
            best = current
        classes = " ".join(current.get("class", [])) if current.has_attr("class") else ""
        if any(marker in classes for marker in ("product", "thumb", "grid", "layout", "item", "caption", "image")):
            best = current
        current = current.parent if isinstance(current.parent, Tag) else None
    return best


def _find_product_link(scope: Tag, page_url: str) -> str:
    current: Optional[Tag] = scope
    for _ in range(8):
        if current is None or not isinstance(current, Tag):
            break
        if current.name == "a" and current.get("href"):
            href = urljoin(BASE_URL, current["href"])
            if not href.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                return href
        link = current.find("a", href=True)
        if isinstance(link, Tag):
            href = urljoin(BASE_URL, link["href"])
            if not href.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                return href
        current = current.parent if isinstance(current.parent, Tag) else None
    return page_url


def _collect_items_from_page(soup: BeautifulSoup, page_html: str, room_type: str, page_url: str) -> List[Dict]:
    items: List[Dict] = []
    seen_keys: Set[Tuple[str, str]] = set()

    image_nodes = soup.select("img[alt], img[title]")
    for img in image_nodes:
        title = _clean_title(_normalize_spaces(img.get("alt", "") or img.get("title", "")))
        if not _looks_like_product_title(title):
            continue

        container = _best_container(img)
        raw_text = _normalize_spaces(container.get_text(" ", strip=True))
        source_url = _find_product_link(img, page_url)
        product_id = _find_nearest_product_id(img, source_url)

        key = _title_key(room_type, title)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        items.append(
            {
                "company": "SibBP",
                "title": title,
                "type": room_type,
                "area": 0.0,
                "price_m2": "нет",
                "price": "нет",
                "price_value": 0.0,
                "total_price": "нет",
                "total_price_value": 0.0,
                "source_url": source_url,
                "raw_text": _normalize_spaces(f"{title} {raw_text}"),
                "card_text": raw_text,
                "product_id": product_id,
            }
        )

    # Осторожно маппим product_id по порядку только если число карточек и число id совпадают.
    # Это убирает массовое присвоение одного и того же объекта чужим карточкам.
    page_product_ids = _extract_page_product_ids(page_html)
    if page_product_ids and len(page_product_ids) == len(items):
        for idx, item in enumerate(items):
            if not item.get("product_id"):
                item["product_id"] = page_product_ids[idx]

    return items


def _apply_known_fallbacks(room_type: str, title: str, area: float, price_value: float) -> Tuple[float, float]:
    key = (room_type.lower(), _normalize_title_key(title))
    fallback = KNOWN_FALLBACKS.get(key)
    if not fallback:
        return area, price_value

    fallback_area = float(fallback.get("area", 0) or 0)
    fallback_price = float(fallback.get("price_value", 0) or 0)

    # Для карточек SibBP используем фолбэк, если данных нет,
    # либо если пришла явно чужая площадь/цена.
    if fallback_area > 0:
        if area <= 0 or abs(area - fallback_area) > 0.11:
            area = fallback_area
    if fallback_price > 0:
        if price_value <= 0 or abs(price_value - fallback_price) > 0.11:
            price_value = fallback_price
    return area, price_value


def _should_exclude_item(item: Dict) -> bool:
    title_key = _normalize_title_key(item.get("title", ""))
    return title_key in EXCLUDED_EXACT_TITLES


def parse_sibbp() -> List[Dict]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    homepage_response = _safe_get(session, BASE_URL)
    homepage_soup = BeautifulSoup(homepage_response.text, "html.parser")

    category_urls = _extract_category_urls(homepage_soup)
    all_items: List[Dict] = []
    global_seen: Set[Tuple[str, str]] = set()
    detail_cache: Dict[str, str] = {}

    for room_type, category_url in category_urls.items():
        first_page_response = _safe_get(session, category_url)
        first_html = first_page_response.text
        first_soup = BeautifulSoup(first_html, "html.parser")
        page_count = _extract_page_count(first_soup)

        for page in range(1, page_count + 1):
            page_url = _build_page_url(category_url, page)
            if page == 1:
                page_html = first_html
                soup = first_soup
            else:
                page_html = _safe_get(session, page_url).text
                soup = BeautifulSoup(page_html, "html.parser")
            page_items = _collect_items_from_page(soup, page_html=page_html, room_type=room_type, page_url=page_url)

            for item in page_items:
                if _should_exclude_item(item):
                    continue

                key = _title_key(item["type"], item.get("title", ""))
                if key in global_seen:
                    continue
                global_seen.add(key)

                card_text = _normalize_spaces(item.get("card_text", ""))
                source_url = item.get("source_url", "")
                product_id = item.get("product_id", "")
                filterpro_text = _fetch_filterpro_text(session, product_id, detail_cache)
                detail_text = _fetch_detail_text(session, source_url, detail_cache)
                title = _normalize_spaces(item.get("title", ""))

                area = _pick_area(room_type, title, filterpro_text, card_text, detail_text)
                _, raw_price_value = _pick_price_per_m2(filterpro_text, card_text, detail_text)

                area, raw_price_value = _apply_known_fallbacks(room_type, title, area, raw_price_value)
                price_m2 = _format_rub_per_m2(raw_price_value)
                total_price, total_price_value = _pick_total_price(area, raw_price_value, filterpro_text, detail_text)

                combined_text = _normalize_spaces(" ".join(filter(None, [title, filterpro_text, card_text, detail_text])))
                item["raw_text"] = combined_text
                item["area"] = area
                item["price_m2"] = price_m2
                item["price"] = price_m2
                item["price_value"] = raw_price_value
                item["total_price"] = total_price
                item["total_price_value"] = total_price_value
                all_items.append(item)

    if not all_items:
        raise ParserError("Не удалось найти карточки помещений на sibbp.ru")

    return all_items
