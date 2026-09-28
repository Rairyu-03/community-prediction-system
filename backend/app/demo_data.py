from __future__ import annotations

from copy import deepcopy

from .defaults import DEFAULT_MIGRATION_RATES, DEFAULT_POPULATION_PARAMETERS, FACILITY_PARAMETER_GROUPS


DEMO_PROJECT_NAME = "默认预测项目"
DEMO_COMMUNITY_CODE = "120101-A"
DEMO_COMMUNITY_NAME = "庆有西里社区"


_QINGYOU_XILI_AGE_COUNTS = (
    71, 110, 104, 105, 78, 137, 177, 203, 207, 171, 134, 168, 132, 119, 125, 107, 122, 87,
    92, 103, 53, 55, 53, 59, 78, 67, 66, 108, 99, 121, 130, 187, 241, 294, 304, 369, 315,
    325, 325, 288, 225, 217, 269, 274, 202, 175, 176, 141, 117, 146, 93, 123, 120, 108, 106,
    125, 108, 100, 69, 92, 102, 89, 161, 106, 51, 81, 73, 81, 73, 66, 73, 61, 50, 47, 32,
    27, 16, 16, 12, 10, 14, 10, 4, 6, 8, 10, 4, 8, 4, 2, 1, 2,
) + (0,) * 29


DEMO_COMMUNITY = {
    "code": DEMO_COMMUNITY_CODE,
    "name": DEMO_COMMUNITY_NAME,
    "region": "天津市",
    "households": 4150,
    "average_household_size": 2.5,
    "migration_rates": deepcopy(DEFAULT_MIGRATION_RATES),
    "age_counts": {str(age): count for age, count in enumerate(_QINGYOU_XILI_AGE_COUNTS)},
    "facilities": {
        "助餐设施": {"社区食堂建筑面积（平方米）": 300},
        "养老设施": {"老年服务站容纳量（人）": 20, "老年服务站建筑面积（平方米）": 375},
        "托育设施": {
            "现有托儿所建筑面积（平方米）": 200,
            "现有托儿所托育人数（人）": 30,
            "现有幼儿园建筑面积（平方米）": 200,
            "现有幼儿园用地面积（平方米）": 200,
            "现有幼儿园托育人数（人）": 30,
        },
        "停车充电设施": {"停车位数量（个）": 467, "机动车充电桩数量（个）": 79},
        "机动车充电桩列表": [
            {"充电桩编号": f"120101-A-7-{index + 1}", "建设年份": 2019 + index % 7}
            for index in range(79)
        ],
    },
    "idle_spaces": [
        {
            "闲置空间编号": "120101-A-8-1",
            "待分配建筑面积（平方米）": 100,
            "待分配用地面积（平方米）": 200,
            "经度": 117.18243322,
            "纬度": 39.12892437,
        },
        {
            "闲置空间编号": "120101-A-8-2",
            "待分配建筑面积（平方米）": 101,
            "待分配用地面积（平方米）": 201,
            "经度": 118.18243322,
            "纬度": 40.12892437,
        },
    ],
}


DEMO_POPULATION_PARAMETERS = deepcopy(DEFAULT_POPULATION_PARAMETERS)
DEMO_POPULATION_PARAMETERS["sourceNotes"] = {
    "birth": "内置案例演示值",
    "death": "内置案例演示值，单位为千分率（‰）",
}


DEMO_FACILITY_PARAMETERS = {
    "status": "ready",
    "missingRequired": [],
    "isDemo": True,
    "meal": {
        "demandRate": 35,
        "diningAreaPerPerson": 1.2,
        "deliveryAreaPerPerson": 0.4,
        "kitchenAreaPerPerson": 0.35,
        "preparationAreaPerPerson": 0.25,
        "diningSpaceAreaPerPerson": 0.6,
    },
    "elderly": {
        "stationDemandRate": 20,
        "stationAreaPerPerson": 3,
        "disabilityRates": {"60-69岁": 6.9, "70-79岁": 12.6, "80岁以上": 29.2},
        "rehabilitationRates": {"60-69岁": 18, "70-79岁": 25, "80岁以上": 32},
        "entertainmentRates": {"60-69岁": 30, "70-79岁": 36, "80岁以上": 40},
        "transportRates": {"60-69岁": 8, "70-79岁": 16, "80岁以上": 28},
    },
    "childcare": {
        "nurseryDemandRate": 40,
        "nurseryAreaPerPerson": 8,
        "kindergartenDemandRate": 85,
        "kindergartenBuildingAreaPerPerson": 8.8,
        "kindergartenLandAreaPerPerson": 15,
        "outdoorAreaPerPerson": 4,
        "sharedAreaPerPerson": 2,
        "combinedRoomAreaPerPerson": 5.5,
        "activityRoomAreaPerPerson": 3.2,
        "bedroomAreaPerPerson": 2.8,
    },
    "parking": {
        "chargerLifetime": 8,
        "chargersPerHousehold": 0.25,
        "parkingSpacesPerHousehold": 1,
        "newEnergyVehiclesPerCapita": {
            str(year): round(0.12 + (year - 2026) * 0.01, 3) for year in range(2026, 2037)
        },
        "vehiclesPerCapita": {
            str(year): round(0.32 + (year - 2026) * 0.005, 3) for year in range(2026, 2037)
        },
    },
    "activity": {"publicAreaPerCapita": 0.3, "sportsAreaPerCapita": 0.1},
    "sourceNotes": "庆有西里社区完整流程演示参数，仅用于功能展示，不代表天津市正式配置标准。",
    "references": {
        path: {
            "standard": None,
            "source": "庆有西里内置案例模拟值（非正式地方标准）",
        }
        for group in FACILITY_PARAMETER_GROUPS.values()
        for _, path in group
    },
    "vehicleSources": {
        str(year): "庆有西里内置案例模拟趋势（非正式统计数据）" for year in range(2026, 2037)
    },
}
