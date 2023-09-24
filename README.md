[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/releases)
![GitHub repo size](https://img.shields.io/github/repo-size/myTselection/MyEnergy.svg)

[![GitHub issues](https://img.shields.io/github/issues/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/commits/master)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/graphs/commit-activity)

# DRAFT !!! UNDER CONSTRUCTION !! My Energy - MijnEnergie.be Home Assistant integration
[Mijn Energie](https://www.mijnenergie.be/) Home Assistant custom component integration for Belgium. This custom component has been built from the ground up to bring MijnEnergie.be site data into Home Assistant sensors in order to follow up energy electricty and gas prices. This integration is built against the public website provided by MijnEnergie.be for Belgium and has not been tested for any other countries.

This integration is in no way affiliated with MijnEnergie.

<p align="center"><img src="https://raw.githubusercontent.com/myTselection/MyEnergy/master/icon.png"/></p>


## Installation
- [HACS](https://hacs.xyz/): add url https://github.com/myTselection/MyEnergy as custom repository (HACS > Integration > option: Custom Repositories)
- Restart Home Assistant
- Add 'MyEnergy' integration via HA Settings > 'Devices and Services' > 'Integrations'



## Integration
Device `MyEnergy [username]` should become available with the following sensors:
- <details><summary><code>MyEnergy [username]</code> with details </summary>

	| Attribute | Description |
	| --------- | ----------- |
	| State     |  |
	|           | TODO |
	|           | TODO |
	
	</details>

## Status
Still some optimisations are planned, see [Issues](https://github.com/myTselection/MyEnergy/issues) section in GitHub.

## Technical pointers
The main logic and API connection related code can be found within source code MyEnergy/custom_components/MyEnery:
- [sensor.py](https://github.com/myTselection/MyEnergy/blob/master/custom_components/MyEnergy/sensor.py)
- [utils.py](https://github.com/myTselection/MyEnergy/blob/master/custom_components/MyEnergy/utils.py) -> mainly ComponentSession class

All other files just contain boilerplat code for the integration to work wtihin HA or to have some constants/strings/translations.

If you would encounter some issues with this custom component, you can enable extra debug logging by adding below into your `configuration.yaml`:
```
logger:
  default: info
  logs:
     custom_components.MyEnergy: debug
```

## Example usage

<details><summary>Click to show the Mardown example</summary>

```
type: markdown
  content: >-
    {{states('sensor.myenergy_[username]')}}  
```
</details>
