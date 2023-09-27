[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/releases)
![GitHub repo size](https://img.shields.io/github/repo-size/myTselection/MyEnergy.svg)

[![GitHub issues](https://img.shields.io/github/issues/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/commits/master)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/myTselection/MyEnergy.svg)](https://github.com/myTselection/MyEnergy/graphs/commit-activity)

# BETA! My Energy - MijnEnergie.be Home Assistant integration
[Mijn Energie](https://www.mijnenergie.be/) Home Assistant custom component integration for Belgium. This custom component has been built from the ground up to bring MijnEnergie.be site data into Home Assistant sensors in order to follow up energy electricty and gas prices. This integration is built against the public website provided by MijnEnergie.be for Belgium and has not been tested for any other countries.

This integration is in no way affiliated with MijnEnergie.

<p align="center"><img src="https://raw.githubusercontent.com/myTselection/MyEnergy/master/icon.png"/></p>


## Installation
- [HACS](https://hacs.xyz/): add url https://github.com/myTselection/MyEnergy as custom repository (HACS > Integration > option: Custom Repositories)
- Restart Home Assistant
- Add 'MyEnergy' integration via HA Settings > 'Devices and Services' > 'Integrations'



## Integration
Device `MyEnergy` should become available with the following sensors:
- <details><summary><code>MyEnergy [postalcode] [FuelType] [ContractType]</code> with details </summary>

	| Attribute | Description |
	| --------- | ----------- |
	| State     | cost in € per kWh  |
	| Last update   | Timestamp of last data refresh, throttled to limit data fetch to 1h |
	| Postalcode    | Postalcode used to retrieve the prices |
	| Fuel type     | Fuel type (Electricity or Gas) used to retrieve the prices |
	| Contract type | Contract type (Fixed or Variable) used to retrieve the prices |
	| Url           | Full url that was used to retrieve the data, throught this url, full details can be seen and contract can be requested |
	| Name          | Name of the cheapest subscription for which a match was found |
	| Energycost    | Energycost (provider dependent part of subscription cost) of the cheapest subscription for which a match was found |
	| Netrate       | Netrate  (fixed part of subscription cost) of the cheapest subscription for which a match was found |
	| Promo         | Promo (provider dependent promotion, part of subscription cost) of the cheapest subscription for which a match was found |
	| Total price per year    | Total price per year of the cheapest subscription for which a match was found |
	| Total kWh per year      | Total kWh per year on wich the lookup is based (total combination of day/night/... consumptions) |
	
	</details>

## Status
Still some optimisations are planned, see [Issues](https://github.com/myTselection/MyEnergy/issues) section in GitHub.

## Technical pointers
The main logic and API connection related code can be found within source code MyEnergy/custom_components/MyEnery:
- [sensor.py](https://github.com/myTselection/MyEnergy/blob/master/custom_components/MyEnergy/sensor.py)
- [utils.py](https://github.com/myTselection/MyEnergy/blob/master/custom_components/MyEnergy/utils.py) -> mainly ComponentSession class

All other files just contain boilerplat code for the integration to work wtihin HA or to have some constants/strings/translations.

If you would encounter some issues with this custom component, you can enable extra debug logging by adding below into your `configuration.yaml`:
<details><summary>Click to show example</summary>
	
```
logger:
  default: info
  logs:
     custom_components.myenergy: debug
```
</details>

## Statistics
In order to keep long term statistics, you could create statistics sensors such as example below (I'm still experimenting with best config):
in `configuration.yaml`:
<details><summary>Click to show example</summary>
	
```
sensor: 
  - platform: statistics
    name: "MyEnergy Electricity Fixed statistics"
    entity_id: sensor.myenergy_[postalcode]_electricty_fixed
    state_characteristic: average_linear
    sampling_size: 20
    max_age:
      hours: 24
  - platform: statistics
    name: "MyEnergy Electricity Variable statistics"
    entity_id: sensor.myenergy_[postalcode]_electricty_variable
    state_characteristic: average_linear
    sampling_size: 20
    max_age:
      hours: 24
  - platform: statistics
    name: "MyEnergy Gas Fixed statistics"
    entity_id: sensor.myenergy_[postalcode]_gas_fixed
    state_characteristic: average_linear
    sampling_size: 20
    max_age:
      hours: 24
  - platform: statistics
    name: "MyEnergy Gas Variable statistics"
    entity_id: sensor.myenergy_[postalcode]_gas_variable
    state_characteristic: average_linear
    sampling_size: 20
    max_age:
      hours: 24
```
</details>

### Statistics Graph
Based on these statistics sensors that will become available after HA rebooted, you can add a Statistics Graph.
<details><summary>Click to show example</summary>


Dashboard:
```
      - chart_type: line
        period: month
        type: statistics-graph
        entities:
          - sensor.myenergy_electricity_fixed_statistics
          - sensor.myenergy_electricity_variable_statistics
          - sensor.myenergy_gas_fixed_statistics
          - sensor.myenergy_gas_variable_statistics
        stat_types:
          - mean
          - min
          - max
        title: Mijn Energie
```
</details>
