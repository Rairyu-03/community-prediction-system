"""Explain stored computations without rerunning against today's edited inputs."""
from ..defaults import FACILITY_PARAMETER_GROUPS


FACILITY_FORMULAS = {
    "未来助餐服务需求人数": "round(60岁及以上人数 × 统一助餐需求率 / 100)",
    "社区食堂建筑面积（堂食模式）": "助餐需求人数 × 堂食人均建筑面积",
    "社区食堂建筑面积缺口（堂食模式）": "堂食建筑面积需求 − 现有食堂建筑面积",
    "社区食堂建筑面积（送餐模式）": "助餐需求人数 × 送餐人均建筑面积",
    "社区食堂厨房建筑面积（堂食模式）": "助餐需求人数 × 厨房人均建筑面积",
    "社区食堂配餐空间建筑面积（堂食模式）": "助餐需求人数 × 配餐空间人均建筑面积",
    "社区食堂用餐空间建筑面积（堂食模式）": "助餐需求人数 × 用餐空间人均建筑面积",
    "生活不能完全自理老年人占比": "Σ(各老年年龄段人数 × 对应失能率 / 100) / 老年总人数 × 100；无人时为0",
    "老年服务站容纳量": "round(60岁及以上人数 × 服务站需求率 / 100)",
    "老年服务站容纳量缺口": "服务站容纳量需求 − 现有容纳量",
    "老年服务站配置建筑面积": "服务站容纳量需求 × 人均建筑面积",
    "老年服务站建筑面积缺口": "服务站建筑面积需求 − 现有建筑面积",
    "日间服务需求人数": "round(Σ各老年年龄段人数 × 对应失能率 / 100)",
    "保健康复服务需求人数": "round(Σ各老年年龄段人数 × 对应康复需求率 / 100)",
    "文化娱乐服务需求人数": "round(Σ各老年年龄段人数 × 对应娱乐需求率 / 100)",
    "交通接送服务需求人数": "round(Σ各老年年龄段人数 × 对应接送需求率 / 100)",
    "托儿所建筑面积": "0—3岁人数 × 入托需求率 / 100 × 托儿所人均建筑面积",
    "幼儿园建筑面积": "4—6岁人数 × 入园率 / 100 × 幼儿园人均建筑面积",
    "幼儿园用地面积": "4—6岁人数 × 入园率 / 100 × 人均用地面积",
    "幼儿园室外活动场地面积": "4—6岁人数 × 入园率 / 100 × 人均室外活动面积",
    "幼儿园全园共用活动场地面积": "4—6岁人数 × 入园率 / 100 × 人均共用活动面积",
    "幼儿园活动室与寝室使用面积（合并建设）": "4—6岁人数 × 入园率 / 100 × 合建人均使用面积",
    "幼儿园活动室使用面积（分开设置）": "4—6岁人数 × 入园率 / 100 × 活动室人均使用面积",
    "幼儿园寝室使用面积（分开设置）": "4—6岁人数 × 入园率 / 100 × 寝室人均使用面积",
    "机动车充电桩缺口数量（户均法）": "round(预测总户数 × 户均充电桩 − 现有充电桩 + 到期充电桩)；到期数不超过现有总数",
    "机动车充电桩缺口数量（新能源车保有量法）": "round(预测总人口 × 当年新能源车人均保有量 − 现有充电桩 + 到期充电桩)",
    "停车位缺口数量（户均法）": "round(预测总户数 × 户均停车位 − 现有停车位)",
    "停车位缺口数量（机动车保有量法）": "round(预测总人口 × 当年机动车人均保有量 − 现有停车位)",
    "公共活动场地面积": "预测总人口 × 人均公共活动面积",
    "多功能运动场地面积": "预测总人口 × 人均多功能运动面积",
}

AUDIT_NOTES = [
    "数据与时间：使用本批次执行时保存的社区资料和参数。人口数据基准年应与预测基准年一致；预测从基准年的下一年开始，报告展示设置范围内的全部预测年份。",
    "人口变化：出生率、死亡率和净迁入率统一使用千分率（‰），计算时均除以1000。先计算出生、分年龄段死亡及年龄增长，再计算各年龄段净迁入迁出，逐年递推。净迁入率为0表示不考虑该年龄段的净迁移。",
    "年龄与随机分配：按单岁年龄人数推演。分年龄段死亡人数先乘率取整，再在该组内随机移除；迁入人口在对应年龄段内随机分配，迁出随机抽取。不追踪个人身份或性别，120岁及以上合并为末龄组。随机种子用于复现相同输入下的计算。",
    "取整与户数：人口及整数需求采用半入取整，恰好±0.5时向远离0的方向取整；面积和比例使用Python round保留两位小数。预测户数按预测人口除以户均人数取整，不直接按起始户数增长。",
    "设施需求：按预测人口及所选设施参数计算。助餐对60岁及以上人口统一使用一个需求率，不区分老年年龄段；养老部分服务按分龄需求率加权；托育按对应幼龄人口、入托或入园率及人均面积计算。",
    "缺口与车辆数据：预测需求减去现有供给得到缺口；正值表示供给不足，负值表示供给富余，0表示供需平衡。选址仅针对正缺口。车辆保有量缺失年份在已知年份间线性插值，范围外取最近端点。充电桩按建设年份和使用年限判断到期。",
    "空间筛选：目前对助餐、养老、公共活动和运动场地进行面积初筛，助餐使用堂食建筑面积缺口。面积达标时优先选择剩余面积较小的一处；全部不达标时展示覆盖率最高的一处。暂不支持托儿所、幼儿园的动态选址，也不进行跨设施空间互斥分配。",
    "使用范围：选址结果未核验GIS服务半径、消防、日照、楼层、权属及污染源等条件，仅供方案初筛，不作为正式审批依据。模拟数据和模拟参数仅用于演示，实际应用前需核实本地资料及适用标准。",
]


def explain_result(run, result):
    data = result.data
    audit = data.get("calculationAudit")
    rows = []
    inputs = []
    snapshot = run.parameters_snapshot
    legacy_migration = run.kind == "population" and snapshot.get("migrationRateUnit") != "‰"
    if run.kind == "facility" and audit:
        population_audit = audit.get("population", {}).get("calculationAudit", {})
        legacy_migration = any("净迁入率（%）" in row for row in population_audit.get("migration", []))
    divisor = 100 if legacy_migration else 1000
    notes = list(AUDIT_NOTES)
    if legacy_migration:
        notes[1] = "历史批次口径：本批次出生率、死亡率使用千分率（除以1000），净迁入率使用百分率（除以100）。保留当时计算和结果，不按新单位重新解释。新执行的人口预测三类比率均使用千分率。"
    if run.kind == "population":
        if audit:
            deaths = sum(item["死亡人数"] for item in audit["deaths"])
            migration = sum(item["净迁移人数"] for item in audit["migration"])
            previous, births = audit["previousPopulation"], audit["births"]
            rows = [
                {"指标": "出生人数", "公式": "round(上年人口 × 当年出生率 / 1000)", "代入": f"round({previous} × {audit['birthRate']} / 1000)", "结果": births},
                {"指标": "总死亡人数", "公式": "Σ round(上年各死亡年龄段人数 × 对应死亡率 / 1000)", "结果": deaths},
                {"指标": "基础存活人数", "公式": "上年人口 + 出生 − 死亡", "代入": f"{previous} + {births} − {deaths}", "结果": previous+births-deaths},
                {"指标": "净迁移人数", "公式": f"Σ round(本年各迁移年龄段存活人数 × 净迁入率 / {divisor})", "结果": migration},
                {"指标": "预测总人口", "公式": "上年人口 + 出生 − 死亡 + 净迁移", "代入": f"{previous} + {births} − {deaths} + {migration}", "结果": data["totalPopulation"]},
                {"指标": "预测总户数", "公式": "round(预测总人口 / 户均人数)", "代入": f"round({data['totalPopulation']} / {audit['averageHouseholdSize']})", "结果": data["households"]},
            ]
            inputs = [{"参数": "请求地区", "值": audit["requestedRegion"]}, {"参数": "实际出生率来源地区", "值": audit["birthRegion"]}]
        else:
            rows = [{"指标": "总人口", "公式": "上年人口 + 出生 − 死亡 + 净迁移", "结果": data.get("totalPopulation")}, {"指标": "户数", "公式": "round(人口/户均人数)", "结果": data.get("households")}]
    else:
        rows = [
            {
                "指标": key,
                "公式": FACILITY_FORMULAS.get(key.split("/", 1)[-1], "未登记公式，请人工核验"),
                "结果": value,
            }
            for key, value in data.get("metrics", {}).items()
        ]
        for definitions in FACILITY_PARAMETER_GROUPS.values():
            for label, path in definitions:
                value = snapshot
                for part in path.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                inputs.append({"参数": label, "值": value})
        if audit:
            from .prediction_service import _series_value
            population = audit["population"]
            inputs = [{"参数": "输入人口批次", "值": audit["populationRunId"]}, {"参数": "当年总人口", "值": population["totalPopulation"]}, {"参数": "当年总户数", "值": population["households"]}] + [{"参数": group, "值": count} for group,count in population["ageGroups"].items()] + inputs
            for path,label in [("parking.newEnergyVehiclesPerCapita","当年新能源车人均保有量"),("parking.vehiclesPerCapita","当年机动车人均保有量")]:
                inputs.append({"参数":label, "值":_series_value(snapshot,path,result.year)})
    return {"runId": run.id, "communityId": result.community_id, "year": result.year, "kind": run.kind, "seed": run.seed, "algorithmVersion": snapshot.get("_algorithmVersion", "旧批次未记录版本"), "hasAudit": bool(audit), "notes": notes, "warning": "该批次未保存完整中间过程，只展示已有结果和参数快照；不能用当前社区资料反推历史输入。新预测批次会保存完整审计数据。" if not audit else "以下输入与中间结果在预测执行时保存，不随当前社区编辑变化。", "rows": rows, "inputs": inputs, "audit": audit, "siteAnalysis": data.get("siteAnalysis", {}), "parameters": snapshot}
