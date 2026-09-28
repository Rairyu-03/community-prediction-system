from __future__ import annotations


AGE_GROUPS: dict[str, tuple[int, int]] = {
    "0-3岁": (0, 3),
    "4-6岁": (4, 6),
    "7-12岁": (7, 12),
    "13-17岁": (13, 17),
    "18-59岁": (18, 59),
    "60-69岁": (60, 69),
    "70-79岁": (70, 79),
    "80岁以上": (80, 120),
}


MORTALITY_GROUPS: dict[str, tuple[int, int]] = {
    "0-4岁": (0, 4),
    "5-9岁": (5, 9),
    "10-14岁": (10, 14),
    "15-19岁": (15, 19),
    "20-24岁": (20, 24),
    "25-29岁": (25, 29),
    "30-34岁": (30, 34),
    "35-39岁": (35, 39),
    "40-44岁": (40, 44),
    "45-49岁": (45, 49),
    "50-54岁": (50, 54),
    "55-59岁": (55, 59),
    "60-64岁": (60, 64),
    "65-69岁": (65, 69),
    "70-74岁": (70, 74),
    "75-79岁": (75, 79),
    "80-84岁": (80, 84),
    "85-89岁": (85, 89),
    "90-94岁": (90, 94),
    "95-99岁": (95, 99),
    "100岁及以上": (100, 120),
}


DEFAULT_MORTALITY_RATES = {
    "0-4岁": 0.25,
    "5-9岁": 0.07,
    "10-14岁": 0.10,
    "15-19岁": 0.11,
    "20-24岁": 0.13,
    "25-29岁": 0.16,
    "30-34岁": 0.22,
    "35-39岁": 0.38,
    "40-44岁": 0.65,
    "45-49岁": 1.11,
    "50-54岁": 1.85,
    "55-59岁": 3.14,
    "60-64岁": 5.39,
    "65-69岁": 8.70,
    "70-74岁": 15.52,
    "75-79岁": 28.00,
    "80-84岁": 51.40,
    "85-89岁": 89.14,
    "90-94岁": 145.95,
    "95-99岁": 190.87,
    "100岁及以上": 221.33,
}


DEFAULT_POPULATION_PARAMETERS = {
    "startYear": 2026,
    "duration": 5,
    "birthRateUnit": "‰",
    "deathRateUnit": "‰",
    "birthRates": {
        "全国": {
            "2026": 5.25,
            "2027": 4.89,
            "2028": 4.57,
            "2029": 4.51,
            "2030": 4.46,
            "2031": 4.43,
            "2032": 4.43,
            "2033": 4.44,
            "2034": 4.48,
            "2035": 4.53,
            "2036": 4.59,
        },
        "天津市": {
            "2026": 5.25,
            "2027": 4.89,
            "2028": 4.57,
            "2029": 4.51,
            "2030": 4.46,
            "2031": 4.43,
            "2032": 4.43,
            "2033": 4.44,
            "2034": 4.48,
            "2035": 4.53,
            "2036": 4.59,
        },
    },
    "deathRates": {
        str(year): DEFAULT_MORTALITY_RATES for year in range(2026, 2037)
    },
    "sourceNotes": {
        "birth": "",
        "death": "",
    },
}


DEFAULT_FACILITY_PARAMETERS = {
    "status": "incomplete",
    "meal": {
        "demandRate": None,
        "diningAreaPerPerson": None,
        "deliveryAreaPerPerson": None,
        "kitchenAreaPerPerson": None,
        "preparationAreaPerPerson": None,
        "diningSpaceAreaPerPerson": None,
    },
    "elderly": {
        "stationDemandRate": None,
        "stationAreaPerPerson": None,
        "disabilityRates": {"60-69岁": 6.9, "70-79岁": 12.6, "80岁以上": 29.2},
        "rehabilitationRates": {"60-69岁": None, "70-79岁": None, "80岁以上": None},
        "entertainmentRates": {"60-69岁": None, "70-79岁": None, "80岁以上": None},
        "transportRates": {"60-69岁": None, "70-79岁": None, "80岁以上": None},
    },
    "childcare": {
        "nurseryDemandRate": None,
        "nurseryAreaPerPerson": None,
        "kindergartenDemandRate": None,
        "kindergartenBuildingAreaPerPerson": None,
        "kindergartenLandAreaPerPerson": None,
        "outdoorAreaPerPerson": None,
        "sharedAreaPerPerson": None,
        "combinedRoomAreaPerPerson": None,
        "activityRoomAreaPerPerson": None,
        "bedroomAreaPerPerson": None,
    },
    "parking": {
        "chargerLifetime": 8,
        "chargersPerHousehold": 1,
        "parkingSpacesPerHousehold": None,
        "newEnergyVehiclesPerCapita": {},
        "vehiclesPerCapita": {},
    },
    "activity": {
        "publicAreaPerCapita": None,
        "sportsAreaPerCapita": None,
    },
    "sourceNotes": "",
}


FACILITY_PARAMETER_GROUPS = {
    "meal": [
        ("老年人助餐服务需求率（%）", "meal.demandRate"),
        ("堂食模式下社区食堂人均配置建筑面积（平方米）", "meal.diningAreaPerPerson"),
        ("堂食模式下社区食堂厨房人均配置建筑面积（平方米）", "meal.kitchenAreaPerPerson"),
        ("堂食模式下社区食堂配餐空间人均配置建筑面积（平方米）", "meal.preparationAreaPerPerson"),
        ("堂食模式下社区食堂用餐空间人均配置建筑面积（平方米）", "meal.diningSpaceAreaPerPerson"),
        ("送餐模式下社区食堂人均配置建筑面积（平方米）", "meal.deliveryAreaPerPerson"),
    ],
    "elderly": [
        ("生活不能完全自理的60-69岁老年人比例（%）", "elderly.disabilityRates.60-69岁"),
        ("生活不能完全自理的70-79岁老年人比例（%）", "elderly.disabilityRates.70-79岁"),
        ("生活不能完全自理的80岁以上老年人比例（%）", "elderly.disabilityRates.80岁以上"),
        ("老年服务站需求率（%）", "elderly.stationDemandRate"),
        ("老年服务站人均配置建筑面积（平方米）", "elderly.stationAreaPerPerson"),
        ("60-69岁老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.60-69岁"),
        ("70-79岁老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.70-79岁"),
        ("80岁以上老年人保健康复服务需求率（%）", "elderly.rehabilitationRates.80岁以上"),
        ("60-69岁老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.60-69岁"),
        ("70-79岁老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.70-79岁"),
        ("80岁以上老年人文化娱乐服务需求率（%）", "elderly.entertainmentRates.80岁以上"),
        ("60-69岁老年人交通接送服务需求率（%）", "elderly.transportRates.60-69岁"),
        ("70-79岁老年人交通接送服务需求率（%）", "elderly.transportRates.70-79岁"),
        ("80岁以上老年人交通接送服务需求率（%）", "elderly.transportRates.80岁以上"),
    ],
    "childcare": [
        ("托儿所人均配置建筑面积（平方米）", "childcare.nurseryAreaPerPerson"),
        ("托儿所入托需求率（%）", "childcare.nurseryDemandRate"),
        ("幼儿园人均配置建筑面积（平方米）", "childcare.kindergartenBuildingAreaPerPerson"),
        ("幼儿园人均配置用地面积（平方米）", "childcare.kindergartenLandAreaPerPerson"),
        ("幼儿园人均配置室外活动场地面积（平方米）", "childcare.outdoorAreaPerPerson"),
        ("幼儿园人均配置全园共用活动场地面积（平方米）", "childcare.sharedAreaPerPerson"),
        ("幼儿园入园需求率（%）", "childcare.kindergartenDemandRate"),
        ("幼儿园人均活动室与寝室使用面积（活动室与寝室合并建设）（平方米）", "childcare.combinedRoomAreaPerPerson"),
        ("幼儿园人均活动室使用面积（活动室与寝室分开建设）（平方米）", "childcare.activityRoomAreaPerPerson"),
        ("幼儿园人均寝室使用面积（活动室与寝室分开建设）（平方米）", "childcare.bedroomAreaPerPerson"),
    ],
    "parking": [
        ("充电桩寿命（年）", "parking.chargerLifetime"),
        ("充电桩配比（个/户）", "parking.chargersPerHousehold"),
        ("停车位配比（个/户）", "parking.parkingSpacesPerHousehold"),
    ],
    "activity": [
        ("人均公共活动场地面积（平方米）", "activity.publicAreaPerCapita"),
        ("人均多功能运动场地面积（平方米）", "activity.sportsAreaPerCapita"),
    ],
}

REQUIRED_FACILITY_PATHS = tuple(
    path for group in FACILITY_PARAMETER_GROUPS.values() for _, path in group
)


DEFAULT_MIGRATION_RATES = {name: 0.0 for name in AGE_GROUPS}
