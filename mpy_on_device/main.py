# minimal_gc9a01_test.py
from machine import Pin, SPI
import gc9a01
import time
import struct
import math # Added for trigonometric functions
import framebuf
import network # For Wi-Fi
import urequests # For HTTP requests
import ujson # For JSON parsing

print("Starting GC9A01 Weather Clock Test...")

# --- Configuration ---
WIFI_SSID = "x"
WIFI_PASS = "x"
LATITUDE = "59.928"
LONGITUDE = "10.673"
# YR.NO API User-Agent: "ApplicationName/Version ContactInfo(email/website)"
YR_USER_AGENT = "ESP32-klokke henrikhildre@gmail.com"

OSLO_UTC_OFFSET = 2 # Oslo is UTC+2 during CEST (Central European Summer Time)

FETCH_INTERVAL_SECONDS = 1800 # Fetch new data every 30 minutes
last_fetch_time = 0 # Shared for YR data
last_uv_fetch_time = 0 # Separate for UV data
weather_data_cache = None
uv_data_cache = None

# Default/Fallback Data
DEFAULT_HOURLY_UV = [1, 7, 1, 7, 1, 7, 1, 7, 1, 7] # 7AM-4PM
DEFAULT_MIN_TEMP = 1
DEFAULT_MAX_TEMP = 45
DEFAULT_ICON_MORNING = ('SUN_32', 'LUT_INDEX_YELLOW')
DEFAULT_ICON_AFTERNOON = ('CLOUD_32', 'LUT_INDEX_WHITE')
DEFAULT_ICON_EVENING = ('RAIN_32', 'LUT_INDEX_WHITE', 'LUT_INDEX_BLUE') # Cloud color, Rain color

# Pins based on Spotpear ESP32-S3-1.28inch-AI User Guide
# DC ---GPIO 10
# CS ---GPIO 13
# SCLK ---GPIO 14
# MOSI ---GPIO 17
# RESET ---GPIO 18
# BL ---GPIO 3
SCK_PIN  = 14
MOSI_PIN = 17
CS_PIN   = 13
DC_PIN   = 10
RST_PIN  = 18
BL_PIN   = 3

# SPI Configuration
# Using SPI(2) (HSPI) by default. ESP32-S3 pins are flexible via GPIO matrix.
# Baudrate 20MHz. Polarity 0, Phase 0. Standard SPI Mode 0.
spi = SPI(2, baudrate=20_000_000, polarity=0, phase=0, 
          sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN))
print("SPI configured.")

# Control Pins
cs_pin_obj  = Pin(CS_PIN, Pin.OUT)
dc_pin_obj  = Pin(DC_PIN, Pin.OUT)
rst_pin_obj = Pin(RST_PIN, Pin.OUT)
bl_pin_obj  = Pin(BL_PIN, Pin.OUT)
print("Control pins configured.")

# Backlight ON
bl_pin_obj.value(1)
print("Backlight ON.")

# Colors (Standard RGB565 hex values)
# RRRRRGGGGGGBBBBB
STANDARD_RED   = 0xF800 # (255,0,0)
STANDARD_GREEN = 0x07E0 # (0,255,0)
STANDARD_BLUE  = 0x001F # (0,0,255)
STANDARD_WHITE = 0xFFFF # (255,255,255)
STANDARD_BLACK = 0x0000 # (0,0,0)
STANDARD_YELLOW = 0xFFE0 # (255,255,0)
STANDARD_ORANGE = 0xFCA0 # (255,165,0) - Adjusted for more standard orange: R=31, G=41, B=0
STANDARD_VIOLET = 0xF81F # (255,0,255) (Magenta-like) R=31,G=0,B=31
STANDARD_DGREY  = 0x8410 # (128,128,128) R=16,G=32,B=16

# LUT indices (can be simple, e.g., 0, 1, 2)
# Using 1, 2, 3 as before for minimal changes to fill logic
LUT_INDEX_RED   = 1
LUT_INDEX_WHITE = 2
LUT_INDEX_BLACK = 3
# For future use if testing green/blue
# LUT_INDEX_GREEN = 4
# LUT_INDEX_BLUE  = 5
LUT_INDEX_GREEN = 4
LUT_INDEX_BLUE  = 5
LUT_INDEX_YELLOW = 6
LUT_INDEX_ORANGE = 7
LUT_INDEX_VIOLET = 8
LUT_INDEX_DGREY  = 9

# Simulated hourly UV data (7 AM to 4 PM - 10 hours)
# Index 0 = 7 AM, Index 5 = 12 PM, Index 9 = 4 PM
HOURLY_UV_DATA = [1, 1, 2, 3, 5, 7, 8, 7, 6, 4] # Covers 7AM to 4PM

def draw_arc_segment(tft, cx, cy, r_outer, r_inner, start_angle_deg, end_angle_deg, color_index, deg_step=0.25):
    print(f"Drawing arc: center=({cx},{cy}), r=({r_inner}-{r_outer}), angle=({start_angle_deg} to {end_angle_deg}), color_idx={color_index}, step={deg_step}deg")
    current_deg = start_angle_deg
    while current_deg <= end_angle_deg:
        theta_rad = math.radians(current_deg)
        cos_theta = math.cos(theta_rad)
        sin_theta = math.sin(theta_rad)
        for r in range(r_inner, r_outer + 1):
            x = round(cx + r * cos_theta)
            y = round(cy + r * sin_theta)
            if 0 <= x < tft.width and 0 <= y < tft.height: # Check boundaries
                 tft.pixel(x, y, color_index)
        current_deg += deg_step
    print("Arc drawing calculations finished.")

def get_uv_color_index(uv_value):
    if uv_value <= 1.4: return LUT_INDEX_GREEN
    elif uv_value <= 3.4: return LUT_INDEX_YELLOW
    elif uv_value <= 7: return LUT_INDEX_ORANGE
    elif uv_value <= 10: return LUT_INDEX_RED
    else: return LUT_INDEX_VIOLET # 11+

def draw_bitmap(tft, x0, y0, pattern_lines, color_idx):
    """
    Plot a '1'-bit mask to the display.
    • pattern_lines – list[str] of equal length (rows of '0'/'1')
    • (x0, y0)      – top-left corner on the GC9A01
    • color_idx     – LUT index you want to use
    """
    for row, line in enumerate(pattern_lines):
        for col, ch in enumerate(line):
            if ch == '1':
                tft.pixel(x0 + col, y0 + row, color_idx)

# Icon Masks (32x32)
SUN_32 = [
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000001111110000000000000",
    "00000000000001111110000000000000",
    "00000000000000111100000000000000",
    "00000001100000111100000110000000",
    "00000011110000111100001111000000",
    "00000111110001111110001111100000",
    "00000111111111111111111111100000",
    "00000011111111111111111111000000",
    "00000000111111111111111100000000",
    "00000000111111111111111100000000",
    "00000000111111111111111100000000",
    "00110001111111111111111110000000",
    "00111111111111111111111110000000",
    "00111111111111111111111110000000",
    "00111111111111111111111111111100",
    "00111111111111111111111111111100",
    "00110001111111111111111110001100",
    "00000000111111111111111100000000",
    "00000000111111111111111100000000",
    "00000000111111111111111100000000",
    "00000011111111111111111111000000",
    "00000111111111111111111111100000",
    "00000111110001111110001111100000",
    "00000011110000111100001111000000",
    "00000001100000111100000110000000",
    "00000000000000111100000000000000",
    "00000000000001111110000000000000",
    "00000000000001111110000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
]

CLOUD_32 = [
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000001000000000000000",
    "00000000000011111111100000000000",
    "00000000000111111111110000000000",
    "00000000001111111111111000000000",
    "00000000011111111111111100000000",
    "00000000111111111111111110000000",
    "00000000111111111111111110000000",
    "00000001111111111111111111110000",
    "00000011111111111111111111111000",
    "00000111111111111111111111111100",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00011111111111111111111111111111",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00000111111111111111111111111100",
    "00000011111111111111111111111000",
    "00000001111111000000011111110000",
    "00000000001000000000000010000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
]

RAIN_32 = [
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000000000000000000000",
    "00000000000000001000000000000000",
    "00000000000011111111100000000000",
    "00000000000111111111110000000000",
    "00000000001111111111111000000000",
    "00000000011111111111111100000000",
    "00000000111111111111111110000000",
    "00000000111111111111111110000000",
    "00000001111111111111111111110000",
    "00000011111111111111111111111000",
    "00000111111111111111111111111100",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00011111111111111111111111111111",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00001111111111111111111111111110",
    "00000111111111111111111111111100",
    "00000011111111111111111111111000",
    "00000001111111001000111111110000",
    "00000000001000000000000010000000",
    "00000000000010001000100000000000",
    "00000000000000000000000000000000",
    "00000000000010001000100000000000",
    "00000000000000000000000000000000",
    "00000000000010001000100000000000",
    "00000000000000000000000000000000",
]

# --- Network Functions ---
def connect_wifi(ssid, password):
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        print(f'Connecting to Wi-Fi (SSID: {ssid})...')
        sta_if.active(True)
        sta_if.connect(ssid, password)
        timeout = 15  # seconds
        start_time = time.time()
        while not sta_if.isconnected() and (time.time() - start_time) < timeout:
            print('.', end='')
            time.sleep(1)
        if sta_if.isconnected():
            print(f'\nConnected! Network config: {sta_if.ifconfig()}')
            return True
        else:
            print('\nWi-Fi connection failed or timed out.')
            sta_if.active(False) # Turn off Wi-Fi to save power if connection failed
            return False
    return True

# YR symbol codes to our icon data and colors
# Format: 'yr_symbol_code': ('ICON_PATTERN_NAME', 'COLOR_LUT_INDEX_NAME', <optional_rain_color_name>)
YR_SYMBOL_TO_ICON = {
    'clearsky_day': (SUN_32, LUT_INDEX_YELLOW),
    'clearsky_night': (SUN_32, LUT_INDEX_DGREY), # Placeholder, maybe moon icon later
    'fair_day': (SUN_32, LUT_INDEX_YELLOW), # Often sun with a bit of cloud
    'partlycloudy_day': (CLOUD_32, LUT_INDEX_WHITE), # More cloud than sun
    'cloudy': (CLOUD_32, LUT_INDEX_DGREY),
    'lightrain': (RAIN_32, LUT_INDEX_WHITE, LUT_INDEX_BLUE), # Cloud color, rain color
    'rain': (RAIN_32, LUT_INDEX_DGREY, LUT_INDEX_BLUE),
    'heavyrain': (RAIN_32, LUT_INDEX_DGREY, LUT_INDEX_BLUE),
    # Add more mappings as needed based on YR symbols
}
DEFAULT_YR_ICON_MAPPING = (CLOUD_32, LUT_INDEX_DGREY) # Fallback if symbol not found

def fetch_uv_data(lat, lon):
    global uv_data_cache, last_uv_fetch_time
    current_time = time.time()

    if uv_data_cache and (current_time - last_uv_fetch_time < FETCH_INTERVAL_SECONDS):
        print("Using cached UV data.")
        return uv_data_cache

    url = f"https://currentuvindex.com/api/v1/uvi?latitude={lat}&longitude={lon}"
    # This API does not strictly require a User-Agent but it's good practice if we had one to set.
    # For now, no specific headers needed unless issues arise.
    print(f"Fetching UV data from: {url}")
    
    hourly_uv_list = list(DEFAULT_HOURLY_UV) # Start with default

    try:
        response = urequests.get(url) # No specific headers for this one
        if response.status_code == 200:
            print("UV API request successful.")
            data = response.json()
            response.close()
            
            # Initialize a list for 10 hours (7AM-4PM local time)
            # We will fill this based on UTC hours from API converted to local time
            # The index 0 corresponds to 7 AM local time.
            processed_uv_forecast = [-1] * 10 # Use -1 to indicate slot not yet filled by a relevant hour
            uv_slots_filled_count = 0

            if 'forecast' in data and isinstance(data['forecast'], list):
                for entry in data['forecast']:
                    entry_time_str = entry.get('time', '')
                    uv_value = entry.get('uvi', 0.0)
                    try:
                        utc_hour = int(entry_time_str.split('T')[1].split(':')[0])
                        local_hour = (utc_hour + OSLO_UTC_OFFSET) % 24
                        
                        # Check if this local_hour falls within our desired 7 AM - 4 PM window
                        if 7 <= local_hour < (7 + 10): # 7 AM (inclusive) to 5 PM (exclusive) -> 7 AM to 4 PM (10 slots)
                            target_index = local_hour - 7 # Index in our 10-slot list (0 for 7AM, 1 for 8AM, ..., 9 for 4PM)
                            if 0 <= target_index < 10 and processed_uv_forecast[target_index] == -1: # Ensure not overwriting if somehow multiple UTC map to same local slot
                                processed_uv_forecast[target_index] = max(0, int(round(float(uv_value))))
                                uv_slots_filled_count +=1
                    except Exception as e:
                        print(f"Error parsing time or UV for UV entry '{entry_time_str}': {e}")
                
                # If we found relevant UV values, use them. Otherwise, defaults will be used.
                if uv_slots_filled_count > 0:
                    # Replace any remaining -1 (unfilled slots) with 0 UV index
                    hourly_uv_list = [val if val != -1 else 0 for val in processed_uv_forecast]
                    print(f"Processed {uv_slots_filled_count} UV values for local time.")
                else:
                    print("No relevant hourly UV data found for local time window, using defaults.")
                    # hourly_uv_list remains DEFAULT_HOURLY_UV as initialized
            else:
                print("UV forecast data not found or not in expected format.")
                # hourly_uv_list remains DEFAULT_HOURLY_UV
            
            uv_data_cache = list(hourly_uv_list) # Cache a copy
            last_uv_fetch_time = current_time
            print(f"--- fetch_uv_data FINISHED ---")
            print(f"  Hourly UV: {hourly_uv_list}")
            print(f"------------------------------")
            return hourly_uv_list
        else:
            print(f"UV API request failed with status code: {response.status_code}")
            response.close()
            return list(DEFAULT_HOURLY_UV)
    except Exception as e:
        print(f"Error fetching or parsing UV data: {e}")
        return list(DEFAULT_HOURLY_UV)

def fetch_yr_weather_data(lat, lon, user_agent):
    global weather_data_cache, last_fetch_time
    current_time = time.time()

    # Check cache first
    if weather_data_cache and (current_time - last_fetch_time < FETCH_INTERVAL_SECONDS):
        print("Using cached YR weather data.")
        return weather_data_cache

    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}" # Back to Compact
    headers = {'User-Agent': user_agent}
    print(f"Fetching YR weather data from: {url}")
    
    try:
        # gc.collect() # Optional: try to free memory before big allocation
        response = urequests.get(url, headers=headers)
        if response.status_code == 200:
            print("YR API request successful. Attempting to parse JSON with response.json()...")
            data = response.json() # Should be fine for compact endpoint
            response.close() 
            print("YR JSON parsing successful.")
            
            extracted_data = {
                # 'hourly_uv': [], # No longer fetching UV from YR.no
                'min_temp': None,
                'max_temp': None,
                'icons': [] 
            }

            # Min/Max Temp Extraction (remains the same)
            temps_today = []
            if 'properties' in data and 'timeseries' in data['properties']:
                for i in range(min(24, len(data['properties']['timeseries']))):
                    ts = data['properties']['timeseries'][i]
                    if ('data' in ts and
                        'instant' in ts['data'] and
                        'details' in ts['data']['instant'] and
                        'air_temperature' in ts['data']['instant']['details']):
                        temps_today.append(ts['data']['instant']['details']['air_temperature'])
                if temps_today:
                    extracted_data['min_temp'] = min(temps_today)
                    extracted_data['max_temp'] = max(temps_today)
                else: 
                    extracted_data['min_temp'] = DEFAULT_MIN_TEMP
                    extracted_data['max_temp'] = DEFAULT_MAX_TEMP
                
                timeseries_data = data.get('properties', {}).get('timeseries', [])
                # Icon Data Extraction (remains the same simplified logic)
                icon_indices_to_check = [0, 6, 12] 
                for i, ts_idx in enumerate(icon_indices_to_check):
                    if ts_idx < len(timeseries_data):
                        ts_entry_for_icon = timeseries_data[ts_idx]
                        symbol_code = None
                        if ('data' in ts_entry_for_icon and 'next_1_hours' in ts_entry_for_icon['data'] and
                           'summary' in ts_entry_for_icon['data']['next_1_hours'] and
                           'symbol_code' in ts_entry_for_icon['data']['next_1_hours']['summary']):
                            symbol_code = ts_entry_for_icon['data']['next_1_hours']['summary']['symbol_code']
                        elif (i == 0 and 'data' in ts_entry_for_icon and 'next_6_hours' in ts_entry_for_icon['data'] and
                             'summary' in ts_entry_for_icon['data']['next_6_hours'] and
                             'symbol_code' in ts_entry_for_icon['data']['next_6_hours']['summary']):
                            symbol_code = ts_entry_for_icon['data']['next_6_hours']['summary']['symbol_code']
                        
                        if symbol_code:
                            icon_map_tuple = YR_SYMBOL_TO_ICON.get(symbol_code, DEFAULT_YR_ICON_MAPPING)
                            extracted_data['icons'].append(icon_map_tuple) 
                        else:
                            print(f"Could not find YR symbol_code for icon slot {i} (timeseries index {ts_idx})")
                            extracted_data['icons'].append(DEFAULT_YR_ICON_MAPPING) 
                    else:
                        print(f"YR Timeseries too short for icon slot {i} (target index {ts_idx})")
                        extracted_data['icons'].append(DEFAULT_YR_ICON_MAPPING)

            # Ensure exactly 3 icons
            while len(extracted_data['icons']) < 3:
                extracted_data['icons'].append(DEFAULT_YR_ICON_MAPPING)
            extracted_data['icons'] = extracted_data['icons'][:3]
            
            weather_data_cache = extracted_data # Cache YR data
            last_fetch_time = current_time
            print(f"--- fetch_yr_weather_data FINISHED ---")
            print(f"  Min Temp: {extracted_data.get('min_temp')}")
            print(f"  Max Temp: {extracted_data.get('max_temp')}")
            #print(f"  Icons Data (len {len(extracted_data.get('icons', []))}): {extracted_data.get('icons')}")
            print(f"--------------------------------------")
            return extracted_data
        else:
            print(f"YR API request failed with status code: {response.status_code}")
            # ... (error handling for YR API)
            response.close() 
            return None # Indicates YR fetch failed
    except Exception as e:
        print(f"Error fetching or parsing YR weather data: {e}")
        return None # Indicates YR fetch failed

# --- Main Application Logic ---
def main():
    # global HOURLY_UV_DATA, min_temp, max_temp, icon1_pattern, icon1_color, icon2_pattern, icon2_color, icon3_pattern, icon3_cloud_color, icon3_rain_color
    # Make them local to main and pass to drawing functions or use from fetched data directly.
    
    current_min_temp = DEFAULT_MIN_TEMP
    current_max_temp = DEFAULT_MAX_TEMP
    current_hourly_uv = list(DEFAULT_HOURLY_UV) # Use a copy

    # Assign default icons first
    # These will hold the actual pattern objects and LUT index values
    icon1_pattern, icon1_color_idx = YR_SYMBOL_TO_ICON.get('clearsky_day', DEFAULT_YR_ICON_MAPPING) # Example default
    icon2_pattern, icon2_color_idx = DEFAULT_YR_ICON_MAPPING
    icon3_pattern, icon3_cloud_color_idx, *icon3_rain_color_idx_list = DEFAULT_ICON_EVENING # Default is a tuple for rain
    icon3_rain_color_idx = icon3_rain_color_idx_list[0] if icon3_rain_color_idx_list else None


    if connect_wifi(WIFI_SSID, WIFI_PASS):
        print("Attempting to fetch live weather data (YR)...")
        yr_live_data = fetch_yr_weather_data(LATITUDE, LONGITUDE, YR_USER_AGENT)
        
        print("Attempting to fetch live UV data...")
        uv_live_data = fetch_uv_data(LATITUDE, LONGITUDE) # This returns a list of UV values directly

        if yr_live_data:
            print("Successfully fetched YR data. Applying to display variables.")
            print(f"--- main() received YR live_data ---")
            print(f"  Min Temp: {yr_live_data.get('min_temp')}")
            print(f"  Max Temp: {yr_live_data.get('max_temp')}")
            #print(f"  Icons Data: {yr_live_data.get('icons')}")
            print(f"------------------------------------")

            min_temp_api = yr_live_data.get('min_temp')
            max_temp_api = yr_live_data.get('max_temp')
            
            if min_temp_api is not None: current_min_temp = min_temp_api
            if max_temp_api is not None: current_max_temp = max_temp_api
            
            icons_from_api = yr_live_data.get('icons', [])
            
            if len(icons_from_api) >= 1 and icons_from_api[0]:
                icon1_pattern, icon1_color_idx = icons_from_api[0] # Tuple: (PATTERN_OBJ, LUT_INDEX_VAL)
            
            if len(icons_from_api) >= 2 and icons_from_api[1]:
                icon2_pattern, icon2_color_idx = icons_from_api[1]

            if len(icons_from_api) >= 3 and icons_from_api[2]:
                icon3_map = icons_from_api[2] 
                icon3_pattern = icon3_map[0] 
                icon3_cloud_color_idx = icon3_map[1]
                if len(icon3_map) > 2 and icon3_map[2]: 
                    icon3_rain_color_idx = icon3_map[2]
                else: 
                    icon3_rain_color_idx = None 
        else:
            print("Failed to fetch YR live data, using YR defaults for temp/icons.")

        # Apply UV data regardless of YR success, as it's from a different source
        if uv_live_data: # fetch_uv_data returns DEFAULT_HOURLY_UV on failure, so it's always a list
            print("Applying UV data to display variables.")
            print(f"--- main() received UV live_data ---")
            print(f"  Hourly UV: {uv_live_data}")
            print(f"----------------------------------")
            current_hourly_uv = uv_live_data
        else:
            # This case should ideally not be hit if fetch_uv_data always returns a list
            print("Failed to fetch UV live data (should receive defaults), using hardcoded UV defaults.")
            current_hourly_uv = list(DEFAULT_HOURLY_UV)

    else:
        print("No Wi-Fi, using all default weather data.")

    tft = None
    try:
        print("Initializing GC9A01 display...")
        tft = gc9a01.GC9A01(spi, cs_pin_obj, dc_pin_obj, rst_pin_obj, usd=True)
        print("Display initialized.")

        tft.greyscale(False)
        print("Populating LUT...")
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_RED * 2, STANDARD_RED)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_WHITE * 2, STANDARD_WHITE)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_BLACK * 2, STANDARD_BLACK)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_GREEN * 2, STANDARD_GREEN)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_BLUE * 2, STANDARD_BLUE)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_YELLOW * 2, STANDARD_YELLOW)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_ORANGE * 2, STANDARD_ORANGE)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_VIOLET * 2, STANDARD_VIOLET)
        struct.pack_into(">H", gc9a01.GC9A01.lut, LUT_INDEX_DGREY * 2, STANDARD_DGREY)
        print("LUT populated.")

        print("Clearing screen to BLACK...")
        tft.fill(LUT_INDEX_BLACK)
        
        cx = 119
        cy = 119
        r_outer = 118
        r_inner = 98

        print(f"Drawing {len(current_hourly_uv)} hourly UV segments (7AM-4PM-ish)...")
        for i in range(len(current_hourly_uv)):
            uv_value = current_hourly_uv[i]
            uv_color_idx = get_uv_color_index(uv_value)
            actual_hour_24 = 7 + i 
            display_hour_12 = actual_hour_24 % 12
            if display_hour_12 == 0: display_hour_12 = 12
            h_calc = display_hour_12 % 12
            segment_start_deg = -90 + (h_calc * 30)
            segment_end_deg = segment_start_deg + 30.5
            draw_arc_segment(tft, cx, cy, r_outer, r_inner, segment_start_deg, segment_end_deg, uv_color_idx)


        print("Adding text labels...")
        font_height = 8
        text_radial_pos = r_inner - (font_height // 2) - 2
        white_text_color = LUT_INDEX_WHITE
        grey_text_color = LUT_INDEX_DGREY
        def draw_hour_label(hour_val_12, label_str, color_idx):
            angle_deg = -90 + (hour_val_12 % 12) * 30
            angle_rad = math.radians(angle_deg)
            text_width = len(label_str) * 8
            tx = round(cx + text_radial_pos * math.cos(angle_rad) - text_width / 2)
            ty = round(cy + text_radial_pos * math.sin(angle_rad) - font_height / 2)
            tft.text(label_str, tx, ty, color_idx)

        draw_hour_label(12, "12", white_text_color)
        draw_hour_label(3, "3", white_text_color)
        draw_hour_label(9, "9", white_text_color)
        other_hours_to_label = [7, 8, 10, 11, 1, 2, 4, 5]
        for hour in other_hours_to_label:
            draw_hour_label(hour, str(hour), grey_text_color)


        print("Adding Min/Max Temperature...")
        temp_text = f"{current_min_temp}/{current_max_temp} C"
        temp_text_width = len(temp_text) * 8
        tx_temp = round(cx - temp_text_width / 2)
        ty_temp = cy + 60 
        tft.text(temp_text, tx_temp, ty_temp, white_text_color)


        print("Adding weather icons...")
        icon_width = 32
        icon_height = 32
        icon_padding = 10 
        total_icons_width = (icon_width * 3) + (icon_padding * 2)
        start_x_icons = cx - total_icons_width // 2
        icon_y_pos = cy - icon_height // 2

        if icon1_pattern and icon1_color_idx is not None: 
            print(f"Drawing icon 1: pattern={bool(icon1_pattern)}, color_idx={icon1_color_idx}")
            draw_bitmap(tft, start_x_icons, icon_y_pos, icon1_pattern, icon1_color_idx)
        
        if icon2_pattern and icon2_color_idx is not None: 
            print(f"Drawing icon 2: pattern={bool(icon2_pattern)}, color_idx={icon2_color_idx}")
            draw_bitmap(tft, start_x_icons + icon_width + icon_padding, icon_y_pos, icon2_pattern, icon2_color_idx)
        
        if icon3_pattern and icon3_cloud_color_idx is not None:
            print(f"Drawing icon 3: pattern={bool(icon3_pattern)}, cloud_color_idx={icon3_cloud_color_idx}, rain_color_idx={icon3_rain_color_idx}")
            draw_bitmap(tft, start_x_icons + (icon_width + icon_padding) * 2, icon_y_pos, icon3_pattern, icon3_cloud_color_idx)
            if icon3_rain_color_idx is not None: 
                rain_drops_coords = [
                    (5, 24), (8, 26), (5, 28), 
                    (15, 25),(18, 27),(15, 29),
                    (25, 24),(28, 26),(25, 28)
                ]
                base_x_icon3 = start_x_icons + (icon_width + icon_padding) * 2
                base_y_icon3 = icon_y_pos
                for dx, dy in rain_drops_coords:
                    if RAIN_32[dy][dx] == '0':
                        tft.pixel(base_x_icon3 + dx, base_y_icon3 + dy, icon3_rain_color_idx)
        
        print("Final display update...")
        tft.show()
        print("Weather display updated. Will sleep and repeat or end.")
        time.sleep(10) # Keep display on for 10s for this test

    except Exception as e:
        print("Error in main loop:")
        import sys
        sys.print_exception(e)
    finally:
        if tft:
            # Optional: tft.fill(LUT_INDEX_BLACK); tft.show(); bl_pin_obj.value(0)
            pass
        print("End of script run.")

if __name__ == '__main__':
    main() 