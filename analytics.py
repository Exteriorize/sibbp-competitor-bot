from typing import Dict, List


def summarize(items: List[Dict]) -> Dict:
    total_area = round(sum(float(x.get("area", 0) or 0) for x in items), 2)
    total_price = 0.0
    priced_items = 0

    for item in items:
        total_value = item.get("total_price_value")
        if not isinstance(total_value, (int, float)):
            total_value = item.get("total_price")
        if isinstance(total_value, (int, float)) and total_value > 0:
            total_price += float(total_value)

        price_value = item.get("price_value")
        if not isinstance(price_value, (int, float)):
            price_value = item.get("price_per_sqm")
        if isinstance(price_value, (int, float)) and price_value > 0:
            priced_items += 1

    total_price = round(total_price, 2)
    avg_price = round(total_price / total_area, 2) if total_area > 0 and total_price > 0 else 0.0

    by_type = {}
    for item in items:
        room_type = item.get("type", "Неизвестно")
        by_type.setdefault(room_type, {"count": 0, "area": 0.0, "total_price": 0.0, "avg_price": 0.0})
        by_type[room_type]["count"] += 1
        by_type[room_type]["area"] += float(item.get("area", 0) or 0)
        total_value = item.get("total_price_value")
        if not isinstance(total_value, (int, float)):
            total_value = item.get("total_price")
        by_type[room_type]["total_price"] += float(total_value or 0)

    for key in by_type:
        by_type[key]["area"] = round(by_type[key]["area"], 2)
        by_type[key]["total_price"] = round(by_type[key]["total_price"], 2)
        area = by_type[key]["area"]
        total = by_type[key]["total_price"]
        by_type[key]["avg_price"] = round(total / area, 2) if area > 0 and total > 0 else 0.0

    return {
        "count": len(items),
        "total_area": total_area,
        "avg_price": avg_price,
        "total_price": total_price,
        "priced_items": priced_items,
        "by_type": by_type,
    }
