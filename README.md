# N-Dot Clock

A modern, customizable clock application with a beautiful dot-matrix display, weather widget, and web integration support.

![N-Dot Clock](<img width="1600" height="960" alt="_C__Users_Mio_Documents_py%20ver_improved_ndot_clock html (4)" src="https://github.com/user-attachments/assets/0fdfe7e4-6268-4253-b6bb-eb9c51a6e568" />)

## Features

- **Dot-Matrix Clock Display**: Elegant 3x5 dot pattern digits with breathing colon animation
- **Multi-Language Support**: English, Russian, and Ukrainian
- **Weather Widget**: Real-time weather information with animated icons
- **Web Integration**: Embedded YouTube and Home Assistant dashboards
- **Customizable**: Adjust colors, brightness, and layout
- **Smooth Animations**: Fluid slide transitions and edit mode
- **Cross-Platform**: Works on Windows, macOS, and Linux

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Mio-of/NdotClock.git
   cd NdotClock
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python ndot_clock_pyqt.py
   ```

## Usage

### Basic Controls

- **Swipe/Click & Drag**: Navigate between slides
- **Long Press (2s)**: Enter edit mode
- **Click on Card (Edit Mode)**: Configure individual slides
- **F11 or Double-Click**: Toggle fullscreen

### Edit Mode

In edit mode, you can:
- Rearrange slides by dragging
- Add new slides (Weather, Custom, YouTube, Home Assistant)
- Configure clock appearance (colors, brightness)
- Delete slides
- Change language

### Customization

#### Clock Settings
- **Brightness**: Adjust overall display brightness
- **Digit Color**: Choose color for time digits
- **Colon Color**: Choose color for the breathing colon
- **Background Color**: Set background color

#### Weather Widget
- Automatically detects your location via IP
- Shows temperature, weather icon, description, and wind speed
- Updates every 10 minutes
- Configurable display options

#### Web Integration
- **YouTube**: Embed any YouTube page
- **Home Assistant**: Connect to your smart home dashboard
- Full browser functionality within the app

## Configuration

Settings are automatically saved to:
- **Windows**: `%APPDATA%\ndot_clock\ndot_clock_slider_settings.json`
- **macOS**: `~/Library/Application Support/ndot_clock/ndot_clock_slider_settings.json`
- **Linux**: `~/.config/ndot_clock/ndot_clock_slider_settings.json`

## Building Standalone Executable

To create a standalone executable with PyInstaller:

1. **Install PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Build the executable**:
   ```bash
   pyinstaller --onefile --windowed --name "NdotClock" --add-data "resources;resources" ndot_clock_pyqt.py
   ```

3. **Find your executable**:
   - Windows: `dist\NdotClock.exe`
   - macOS/Linux: `dist/NdotClock`

## Project Structure

```
NdotClock/
├── ndot_clock_pyqt.py           # Main application file
├── requirements.txt              # Python dependencies
├── .gitignore                    # Git ignore rules
├── README.md                     # This file
└── resources/                    # Application resources
    ├── *.ttf, *.otf, *.woff     # Custom fonts
    └── *.svg                     # Weather icons
```

## Dependencies

- **PyQt6**: Modern GUI framework
- **PyQt6-WebEngine**: Web browser integration

See [requirements.txt](requirements.txt) for specific versions.

## Performance Optimizations

- **Smart Repaint**: Only updates when necessary (time changes, animations, interactions)
- **Efficient Caching**: Pixmap cache for frequently drawn elements
- **Minimal CPU Usage**: ~80% reduction in idle CPU usage compared to constant repainting

## Cross-Platform Compatibility

- Uses platform-specific paths for configuration
- HTTPS for all network requests
- Works with PyInstaller for standalone executables
- Tested on Windows, macOS, and Linux

## Troubleshooting

### Weather Not Loading
- Check your internet connection
- Ensure firewall allows the application to access the internet
- Weather updates every 10 minutes

### WebView Issues
- Ensure PyQt6-WebEngine is installed: `pip install PyQt6-WebEngine`
- On Linux, you may need to install additional Qt WebEngine dependencies

### High Memory Usage
- WebView components (YouTube/Home Assistant) use 50-150MB each
- Consider closing unused web slides if memory is limited

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is open source and available under the [MIT License](LICENSE).

## Acknowledgments

- Weather data provided by [Open-Meteo](https://open-meteo.com/)
- Geolocation by [ipapi.co](https://ipapi.co/)
- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)

## Author

**Your Name**
- GitHub: [@Mio-of](https://github.com/Mio-of)

## Support

If you encounter any issues or have questions, please [open an issue](https://github.com/yourusername/NdotClock/issues) on GitHub.

---

Made with ❤️ using PyQt6
