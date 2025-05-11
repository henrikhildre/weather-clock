# ESP32-S3 GC9A01 Weather Clock

This project is a weather display and UV index clock for an ESP32-S3 microcontroller equipped with a 1.28-inch round GC9A01 LCD display. It fetches live weather data and UV index information from online APIs and presents it in a user-friendly graphical format.

## Features

*   Time-based UV Index ring (7 AM - 4 PM local time for Oslo, Norway)
*   Min/Max daily temperature display
*   3-hour interval weather forecast icons (current, +6h, +12h)
*   Customizable Wi-Fi credentials
*   Utilizes MicroPython for application logic

## Hardware Requirements

*   ESP32-S3 based development board (e.g., Spotpear ESP32-S3-1.28inch-AI or similar)
*   GC9A01 1.28-inch Round LCD Display (240x240 resolution)
*   Internet connectivity via Wi-Fi

## Software & Dependencies

*   **MicroPython Firmware:** The ESP32-S3 must be flashed with MicroPython. This project potentially uses a custom build (see `micropython/` submodule).
*   **Display Driver:** `gc9a01.py` (included in `mpy_on_device/lib/`)
*   **External Libraries (MicroPython):**
    *   `urequests` for HTTP GET requests
    *   `ujson` for JSON parsing
    *   `network` for Wi-Fi connectivity
    *   `utime` (or `time`) for time-related functions
    *   `machine` for hardware pin and SPI control
    *   `math` for calculations
    *   `struct` for LUT population
    *   `framebuf` (though `draw_bitmap` is custom, `framebuf` is a common MicroPython graphics tool)
*   **APIs Used:**
    *   [YR.no Weather Forecast API](https://api.met.no/) (specifically the `compact` endpoint) for general weather data (temperature, forecast symbols).
    *   [Current UV Index API](https://currentuvindex.com/api) for hourly UV index forecast.

## Project Structure

```
clock/
├── .git/
├── .gitignore
├── .gitmodules
├── mpy_on_device/        # MicroPython code to be deployed to the device
│   ├── main.py         # Main application script
│   └── lib/
│       └── gc9a01.py   # GC9A01 display driver
├── micropython/          # Git submodule for MicroPython source/build
├── lvgl-mpy/             # Git submodule for LVGL MicroPython bindings (if used for firmware)
├── main/                 # (If used) C/C++ source for ESP-IDF components
├── CMakeLists.txt        # Main CMake file for ESP-IDF project
├── sdkconfig             # ESP-IDF project configuration
├── README.md
└── ... (other project files like .devcontainer/)
```

## Setup & Deployment

### 1. Firmware (ESP-IDF & MicroPython)

If you are building the MicroPython firmware from source using the included `micropython` submodule (and potentially `lvgl-mpy`):
1.  Ensure you have the ESP-IDF (Espressif IoT Development Framework) environment set up. Refer to the [official ESP-IDF documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/index.html).
2.  Initialize the submodules:
    ```bash
    git submodule update --init --recursive
    ```
3.  Follow the build instructions within the `micropython/ports/esp32` directory to compile and flash the firmware to your ESP32-S3 board. You may need to configure specific components via `idf.py menuconfig` (e.g., SPI, PSRAM if your board has it).

If you are using a pre-built MicroPython firmware for your ESP32-S3, ensure it includes the necessary modules (`urequests`, `ujson`).

### 2. MicroPython Application

1.  **Configure Wi-Fi Credentials & Location:**
    Edit `mpy_on_device/main.py` to set your:
    *   `WIFI_SSID`
    *   `WIFI_PASS`
    *   `LATITUDE` and `LONGITUDE` for weather data accuracy.
    *   `YR_USER_AGENT` (provide a descriptive user agent, e.g., "MyWeatherClock/1.0 myemail@example.com")
    *   `OSLO_UTC_OFFSET` if your local timezone differs significantly from the default UTC+2 (Oslo summer time) used for UV index display.

2.  **Install `mpremote` (if not already installed):**
    `mpremote` is a tool for interacting with MicroPython devices.
    ```bash
    pip install mpremote
    ```

3.  **Copy Files to ESP32-S3:**
    Connect your ESP32-S3 to your computer.
    Use `mpremote` to copy the application files to the device's root filesystem. From the `clock` directory:
    ```bash
    # Create /lib directory on device if it doesn't exist
    mpremote fs mkdir /lib
    
    # Copy the main script
    mpremote cp mpy_on_device/main.py :main.py
    
    # Copy the display driver
    mpremote cp mpy_on_device/lib/gc9a01.py :/lib/gc9a01.py
    ```
    Alternatively, to copy all contents of `mpy_on_device` (if you had more in lib, for example):
    ```bash
    # Ensure mpy_on_device/main.py and mpy_on_device/lib/gc9a01.py exist
    mpremote cp -r mpy_on_device/* : 
    # Note: This might try to create mpy_on_device on the target. 
    # It's often safer to copy specific files/dirs as above or one by one.
    # A more robust recursive copy of contents might be:
    # mpremote fs cp -r mpy_on_device/lib :/
    # mpremote fs cp mpy_on_device/main.py :
    ```
    The simpler individual `cp` commands listed first are generally reliable.


4.  **Run:**
    After copying the files, the ESP32-S3 should automatically run `main.py` upon reset or power cycle.
    You can also trigger a soft reset via `mpremote`:
    ```bash
    mpremote reset
    ```
    To monitor the output (print statements):
    ```bash
    mpremote repl
    ```
    Then press Ctrl+D in the REPL for a soft reboot, or trigger a hard reset.

## Troubleshooting

*   **Memory Errors:** If you encounter `MemoryError` during API calls, ensure `gc.collect()` is used strategically, or consider parsing JSON data in chunks if possible (though `ujson` on MicroPython has limitations here). The current split API approach aims to mitigate this.
*   **Wi-Fi Connection Issues:** Double-check SSID and password. Ensure your ESP32-S3 has good Wi-Fi signal.
*   **API Failures:**
    *   Ensure your `YR_USER_AGENT` is set and unique for the YR.no API.
    *   Check internet connectivity.
    *   APIs might change or have rate limits.
*   **Display Issues:** Verify pin connections (SCK, MOSI, CS, DC, RST, BL) match those in `main.py`. Ensure the `gc9a01.py` driver is correctly loaded.

## Future Enhancements

*   Implement robust timezone handling using `time.localtime()` and `time.mktime()` if an RTC is set/synced.
*   Add more weather icons and map more YR.no symbol codes.
*   Button controls for different display modes or settings.
*   Configuration file on device (`config.json`) for Wi-Fi, location, etc., to avoid re-flashing `main.py` for changes.
*   Low power mode / deep sleep between updates.
---

Replace `<URL_FOR_MICROPYTHON>` and `<URL_FOR_LVGL_MPY>` in the submodule commands above with the actual URLs if you go that route. If `micropython` and `lvgl-mpy` are already present and you're just formalizing them as submodules within a new parent git repo, the submodule add command might work slightly differently or you might need `git submodule init` after `add`. The key is that `.gitmodules` file gets created correctly. 