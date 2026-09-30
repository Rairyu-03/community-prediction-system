"""Synthetic data used only by acceptance-test scripts."""
from __future__ import annotations

from copy import deepcopy

from app.defaults import DEFAULT_FACILITY_PARAMETERS, DEFAULT_POPULATION_PARAMETERS


SAMPLE_POPULATION_PARAMETERS = deepcopy(DEFAULT_POPULATION_PARAMETERS)

SAMPLE_FACILITY_PARAMETERS = deepcopy(DEFAULT_FACILITY_PARAMETERS)
SAMPLE_FACILITY_PARAMETERS["meal"].update({"demandRate": 35, "diningAreaPerPerson": 1.2, "deliveryAreaPerPerson": 0.4, "kitchenAreaPerPerson": 0.35, "preparationAreaPerPerson": 0.25, "diningSpaceAreaPerPerson": 0.6})
SAMPLE_FACILITY_PARAMETERS["elderly"].update({"stationDemandRate": 20, "stationAreaPerPerson": 3, "rehabilitationRates": {"60-69岁": 18, "70-79岁": 25, "80岁以上": 32}, "entertainmentRates": {"60-69岁": 30, "70-79岁": 36, "80岁以上": 40}, "transportRates": {"60-69岁": 8, "70-79岁": 16, "80岁以上": 28}})
SAMPLE_FACILITY_PARAMETERS["childcare"].update({"nurseryDemandRate": 40, "nurseryAreaPerPerson": 8, "kindergartenDemandRate": 85, "kindergartenBuildingAreaPerPerson": 8.8, "kindergartenLandAreaPerPerson": 15, "outdoorAreaPerPerson": 4, "sharedAreaPerPerson": 2, "combinedRoomAreaPerPerson": 5.5, "activityRoomAreaPerPerson": 3.2, "bedroomAreaPerPerson": 2.8})
SAMPLE_FACILITY_PARAMETERS["parking"].update({"chargersPerHousehold": 0.25, "parkingSpacesPerHousehold": 1, "newEnergyVehiclesPerCapita": {str(year): round(0.12 + (year - 2026) * 0.01, 3) for year in range(2026, 2037)}, "vehiclesPerCapita": {str(year): round(0.32 + (year - 2026) * 0.005, 3) for year in range(2026, 2037)}})
SAMPLE_FACILITY_PARAMETERS["activity"].update({"publicAreaPerCapita": 0.3, "sportsAreaPerCapita": 0.1})

SAMPLE_FACILITIES = {
    "助餐设施": {"社区食堂建筑面积（平方米）": 300},
    "养老设施": {"老年服务站容纳量（人）": 20, "老年服务站建筑面积（平方米）": 375},
    "托育设施": {"现有托儿所建筑面积（平方米）": 200, "现有托儿所托育人数（人）": 30, "现有幼儿园建筑面积（平方米）": 200, "现有幼儿园用地面积（平方米）": 200, "现有幼儿园托育人数（人）": 30},
    "停车充电设施": {"停车位数量（个）": 467, "机动车充电桩数量（个）": 20},
}
