import httpx
from bs4 import BeautifulSoup
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.util import get_ip_info
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

GET_WEATHER_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "获取某个地点的天气，用户应提供一个位置，比如用户说杭州天气，参数为：杭州。"
            "如果用户说的是省份，默认用省会城市。如果用户说的不是省份或城市而是一个地名，默认用该地所在省份的省会城市。"
            "重要：本地未来7天天气已在上下文中提供，用户未指明其他城市时绝对不要调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "地点名，例如杭州。可选参数，如果不提供则不传",
                },
                "lang": {
                    "type": "string",
                    "description": "返回用户使用的语言code，例如zh_CN/zh_HK/en_US/ja_JP等，默认zh_CN",
                },
            },
            "required": ["lang"],
        },
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
    )
}

# 天气代码 https://dev.qweather.com/docs/resource/icons/#weather-icons
WEATHER_CODE_MAP = {
    "100": "晴",
    "101": "多云",
    "102": "少云",
    "103": "晴间多云",
    "104": "阴",
    "150": "晴",
    "151": "多云",
    "152": "少云",
    "153": "晴间多云",
    "300": "阵雨",
    "301": "强阵雨",
    "302": "雷阵雨",
    "303": "强雷阵雨",
    "304": "雷阵雨伴有冰雹",
    "305": "小雨",
    "306": "中雨",
    "307": "大雨",
    "308": "极端降雨",
    "309": "毛毛雨/细雨",
    "310": "暴雨",
    "311": "大暴雨",
    "312": "特大暴雨",
    "313": "冻雨",
    "314": "小到中雨",
    "315": "中到大雨",
    "316": "大到暴雨",
    "317": "暴雨到大暴雨",
    "318": "大暴雨到特大暴雨",
    "350": "阵雨",
    "351": "强阵雨",
    "399": "雨",
    "400": "小雪",
    "401": "中雪",
    "402": "大雪",
    "403": "暴雪",
    "404": "雨夹雪",
    "405": "雨雪天气",
    "406": "阵雨夹雪",
    "407": "阵雪",
    "408": "小到中雪",
    "409": "中到大雪",
    "410": "大到暴雪",
    "456": "阵雨夹雪",
    "457": "阵雪",
    "499": "雪",
    "500": "薄雾",
    "501": "雾",
    "502": "霾",
    "503": "扬沙",
    "504": "浮尘",
    "507": "沙尘暴",
    "508": "强沙尘暴",
    "509": "浓雾",
    "510": "强浓雾",
    "511": "中度霾",
    "512": "重度霾",
    "513": "严重霾",
    "514": "大雾",
    "515": "特强浓雾",
    "900": "热",
    "901": "冷",
    "999": "未知",
}


async def fetch_city_info(location, api_key, api_host):
    url = f"https://{api_host}/geo/v2/city/lookup?key={api_key}&location={location}&lang=zh"
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
        response = await client.get(url, headers=HEADERS)
    data = response.json()
    if data.get("error") is not None:
        logger.bind(tag=TAG).error(
            f"获取天气失败，原因：{data.get('error', {}).get('detail')}"
        )
        return None
    return data.get("location", [])[0] if data.get("location") else None


async def fetch_weather_page(url):
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
        response = await client.get(url, headers=HEADERS)
    return BeautifulSoup(response.text, "html.parser") if response.status_code == 200 else None


def is_placeholder_key(api_key: str) -> bool:
    value = str(api_key or "").strip()
    return not value or value in {"xxx", "your-api-key"} or "你的" in value


async def fetch_amap_city_info(location, api_key):
    url = "https://restapi.amap.com/v3/config/district"
    params = {
        "keywords": location,
        "subdistrict": 0,
        "extensions": "base",
        "key": api_key,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        response = await client.get(url, params=params, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "1":
        return None, data.get("info") or data.get("infocode") or "高德行政区查询失败"

    districts = data.get("districts") or []
    if not districts:
        return None, f"未找到城市：{location}"

    location_text = str(location or "").strip()
    preferred_names = {location_text}
    if location_text and not location_text.endswith(("市", "省", "区", "县")):
        preferred_names.add(f"{location_text}市")

    district = None
    for item in districts:
        if item.get("level") == "city" and item.get("name") in preferred_names:
            district = item
            break
    if district is None:
        for item in districts:
            if item.get("level") == "city":
                district = item
                break
    if district is None:
        district = districts[0]

    adcode = district.get("adcode")
    if not adcode:
        return None, f"未找到城市编码：{location}"

    return {
        "name": district.get("name") or location,
        "adcode": adcode,
    }, None


async def fetch_amap_weather(adcode, api_key, extensions):
    url = "https://restapi.amap.com/v3/weather/weatherInfo"
    params = {
        "city": adcode,
        "key": api_key,
        "extensions": extensions,
        "output": "JSON",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        response = await client.get(url, params=params, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "1":
        return None, data.get("info") or data.get("infocode") or "高德天气查询失败"
    return data, None


def format_amap_weather(city_name, live_data, forecast_data):
    lines = [f"您查询的位置是：{city_name}"]

    lives = (live_data or {}).get("lives") or []
    if lives:
        live = lives[0]
        lines.extend(
            [
                "",
                f"当前天气：{live.get('weather', '未知')}",
                f"温度：{live.get('temperature', '未知')}℃",
                f"风向：{live.get('winddirection', '未知')}",
                f"风力：{live.get('windpower', '未知')}级",
                f"湿度：{live.get('humidity', '未知')}%",
                f"发布时间：{live.get('reporttime', '未知')}",
            ]
        )

    forecasts = (forecast_data or {}).get("forecasts") or []
    casts = forecasts[0].get("casts") if forecasts else []
    if casts:
        lines.append("")
        lines.append("未来天气预报：")
        for item in casts:
            date = item.get("date", "")
            day_weather = item.get("dayweather", "未知")
            night_weather = item.get("nightweather", "未知")
            day_temp = item.get("daytemp", "未知")
            night_temp = item.get("nighttemp", "未知")
            day_wind = item.get("daywind", "未知")
            night_wind = item.get("nightwind", "未知")
            lines.append(
                f"{date}: 白天{day_weather}，夜间{night_weather}，气温 {night_temp}~{day_temp}℃，风向 {day_wind}/{night_wind}"
            )

    if len(lines) == 1:
        return "天气接口返回为空，请检查城市名称或高德Key权限。"

    return "\n".join(lines)


async def get_weather_from_amap(location, api_key):
    if is_placeholder_key(api_key):
        return "高德天气功能还没有配置真实API Key，请在 data/.config.yaml 中配置 plugins.get_weather.api_key。"

    city_info, city_error = await fetch_amap_city_info(location, api_key)
    if city_error:
        return f"高德城市查询失败：{city_error}"

    live_data, live_error = await fetch_amap_weather(city_info["adcode"], api_key, "base")
    forecast_data, forecast_error = await fetch_amap_weather(
        city_info["adcode"], api_key, "all"
    )

    if live_error and forecast_error:
        return f"高德天气查询失败：{live_error}；{forecast_error}"

    return format_amap_weather(city_info["name"], live_data, forecast_data)


def parse_weather_info(soup):
    city_name = soup.select_one("h1.c-submenu__location").get_text(strip=True)

    current_abstract = soup.select_one(".c-city-weather-current .current-abstract")
    current_abstract = (
        current_abstract.get_text(strip=True) if current_abstract else "未知"
    )

    current_basic = {}
    for item in soup.select(
        ".c-city-weather-current .current-basic .current-basic___item"
    ):
        parts = item.get_text(strip=True, separator=" ").split(" ")
        if len(parts) == 2:
            key, value = parts[1], parts[0]
            current_basic[key] = value

    temps_list = []
    for row in soup.select(".city-forecast-tabs__row")[:7]:  # 取前7天的数据
        date = row.select_one(".date-bg .date").get_text(strip=True)
        weather_code = (
            row.select_one(".date-bg .icon")["src"].split("/")[-1].split(".")[0]
        )
        weather = WEATHER_CODE_MAP.get(weather_code, "未知")
        temps = [span.get_text(strip=True) for span in row.select(".tmp-cont .temp")]
        high_temp, low_temp = (temps[0], temps[-1]) if len(temps) >= 2 else (None, None)
        temps_list.append((date, weather, high_temp, low_temp))

    return city_name, current_abstract, current_basic, temps_list


@register_function("get_weather", GET_WEATHER_FUNCTION_DESC, ToolType.SYSTEM_CTL)
async def get_weather(conn: "ConnectionHandler", location: str = None, lang: str = "zh_CN"):
    from core.utils.cache.manager import cache_manager, CacheType

    weather_config = conn.config.get("plugins", {}).get("get_weather", {})
    provider = weather_config.get("provider", "qweather").lower()
    api_host = weather_config.get("api_host", "mj7p3y7naa.re.qweatherapi.com")
    api_key = weather_config.get("api_key", "")
    default_location = weather_config.get("default_location", "广州")
    client_ip = conn.client_ip

    # 优先使用用户提供的location参数
    if not location:
        # 通过客户端IP解析城市
        if client_ip:
            # 先从缓存获取IP对应的城市信息
            cached_ip_info = cache_manager.get(CacheType.IP_INFO, client_ip)
            if cached_ip_info:
                location = cached_ip_info.get("city")
            else:
                # 缓存未命中，调用API获取
                ip_info = get_ip_info(client_ip, logger)
                if ip_info:
                    cache_manager.set(CacheType.IP_INFO, client_ip, ip_info)
                    location = ip_info.get("city")

            if not location:
                location = default_location
        else:
            # 若无IP，使用默认位置
            location = default_location
    # 尝试从缓存获取完整天气报告
    weather_cache_key = f"full_weather_{provider}_{location}_{lang}"
    cached_weather_report = cache_manager.get(CacheType.WEATHER, weather_cache_key)
    if cached_weather_report:
        return ActionResponse(Action.REQLLM, cached_weather_report, None)

    if provider == "amap":
        try:
            weather_report = await get_weather_from_amap(location, api_key)
            cache_manager.set(CacheType.WEATHER, weather_cache_key, weather_report)
            return ActionResponse(Action.REQLLM, weather_report, None)
        except httpx.TimeoutException:
            logger.bind(tag=TAG).error("高德天气请求超时")
            return ActionResponse(Action.REQLLM, "高德天气请求超时，请稍后重试。", None)
        except httpx.HTTPStatusError as e:
            logger.bind(tag=TAG).error(f"高德天气HTTP请求失败: {e}")
            return ActionResponse(Action.REQLLM, "高德天气HTTP请求失败，请检查网络或Key权限。", None)
        except Exception as e:
            logger.bind(tag=TAG).error(f"高德天气查询异常: {e}")
            return ActionResponse(Action.REQLLM, f"高德天气查询异常：{e}", None)

    if provider not in ("qweather", "hefeng", "heweather"):
        return ActionResponse(
            Action.REQLLM,
            f"天气源配置无效：{provider}。当前支持 amap 或 qweather。",
            None,
        )

    # 缓存未命中，获取实时天气数据
    city_info = await fetch_city_info(location, api_key, api_host)
    if not city_info:
        return ActionResponse(
            Action.REQLLM, f"未找到相关的城市: {location}，请确认地点是否正确", None
        )
    soup = await fetch_weather_page(city_info["fxLink"])
    if not soup:
        return ActionResponse(Action.REQLLM, None, "请求失败")
    city_name, current_abstract, current_basic, temps_list = parse_weather_info(soup)

    weather_report = f"您查询的位置是：{city_name}\n\n当前天气: {current_abstract}\n"

    # 添加有效的当前天气参数
    if current_basic:
        weather_report += "详细参数：\n"
        for key, value in current_basic.items():
            if value != "0":  # 过滤无效值
                weather_report += f"  · {key}: {value}\n"

    # 添加7天预报
    weather_report += "\n未来7天预报：\n"
    for date, weather, high, low in temps_list:
        weather_report += f"{date}: {weather}，气温 {low}~{high}\n"

    # 提示语
    weather_report += "\n（如需某一天的具体天气，请告诉我日期）"

    # 缓存完整的天气报告
    cache_manager.set(CacheType.WEATHER, weather_cache_key, weather_report)

    return ActionResponse(Action.REQLLM, weather_report, None)
