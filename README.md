# ESPHome Dashboard Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that connects to your ESPHome Dashboard to provide firmware update entities for your ESPHome devices.

## Features

- **Firmware Update Entities**: Creates update entities for each device configured in your ESPHome Dashboard
- **OTA Updates**: Compile and upload firmware directly from Home Assistant
- **Device Linking**: Automatically links update entities to existing ESPHome devices via MAC address
- **Authentication Support**: Supports dashboards with HTTP Basic Authentication
- **Multiple Dashboards**: Configure multiple ESPHome Dashboard instances

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/idstein/hacs_esphome_dashboard` as a custom repository with category "Integration"
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Copy the `custom_components/esphome_dashboard` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "ESPHome Dashboard"
4. Enter your ESPHome Dashboard URL (e.g., `http://192.168.1.100:6052`)
5. Optionally enter username and password if your dashboard requires authentication

## Usage

After configuration, the integration will create:

- **Update entities** for each device configured in your ESPHome Dashboard
- These entities show the currently installed firmware version vs. the available version
- Use the "Install" action to compile and upload firmware via OTA

### Update Entity Features

- Shows installed version (firmware running on device)
- Shows latest version (from YAML configuration)
- Supports OTA firmware installation when device address is available
- Links to existing ESPHome device entities when MAC address matches

## Requirements

- Home Assistant 2024.1.0 or newer
- ESPHome Dashboard accessible via HTTP/HTTPS
- Python package: `esphome-dashboard-api==1.3.0` (installed automatically)

## Troubleshooting

### Cannot connect to dashboard
- Verify the URL is correct and accessible from your Home Assistant instance
- Check if the dashboard requires authentication
- Ensure no firewall is blocking the connection

### Authentication failed
- Verify your username and password are correct
- Use the "Reconfigure" option to update credentials

### Update entity shows no address
- The device may be offline or not reachable
- OTA updates require the device to have a valid network address

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Credits

This integration is based on the ESPHome Dashboard integration from the Home Assistant core repository.
