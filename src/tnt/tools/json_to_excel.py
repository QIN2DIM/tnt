"""
数据转换器：将docker compose扫描结果JSON转换为Excel表格
"""

import json
import os
from contextlib import suppress
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from openpyxl.styles import Font

from tnt.tools.constant import STORAGE_DIR, STATS_EXCEL_FILENAME


def convert_list_to_str(value: Any) -> str:
    """将列表类型数据转换为字符串"""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value) if value is not None else ""


def load_json_data(json_file: str) -> List[Dict]:
    """加载JSON数据"""
    file_path = Path(json_file)
    if not file_path.exists():
        raise FileNotFoundError(f"JSON文件不存在: {json_file}")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_services_data(composers_data: List[Dict]) -> List[Dict]:
    """提取所有services数据"""
    services_list = []

    for composer in composers_data:
        hostname = composer.get("hostname", "")
        project_name = composer.get("name", "")
        project_status = composer.get("status", "")
        config_files = composer.get("config_files", "")

        for service in composer.get("services", []):
            service_data = {
                "项目主机名": hostname,
                "项目名称": project_name,
                "项目状态": project_status,
                "配置文件": config_files,
                "服务名称": service.get("name", ""),
                "镜像": service.get("image", ""),
                "重启策略": service.get("restart", ""),
                "容器名称": service.get("container_name", ""),
                "网络": convert_list_to_str(service.get("networks", [])),
                "环境文件": convert_list_to_str(service.get("env_file", [])),
                "端口": convert_list_to_str(service.get("ports", [])),
                "挂载卷": convert_list_to_str(service.get("volumes", [])),
                "依赖GPU": service.get("is_depend_on_gpu", False),
                "容器环境变量": convert_list_to_str(service.get("container_env", [])),
            }
            services_list.append(service_data)

    return services_list


def convert_json_to_excel(json_file: str, output_file: str = ""):
    """转换JSON到Excel"""
    # 加载数据
    composers_data = load_json_data(json_file)

    # 提取services数据
    services_data = extract_services_data(composers_data)

    if not services_data:
        print("没有找到services数据")
        return

    # 创建DataFrame
    df = pd.DataFrame(services_data)

    # 生成输出文件名
    if not output_file:
        json_path = Path(json_file)
        output_file = json_path.parent / f"{json_path.stem}_services.xlsx"

    # 保存到Excel
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Services", index=False)

        # 设置字体为微软雅黑
        worksheet = writer.sheets["Services"]
        font = Font(name="微软雅黑", size=10)

        for row in worksheet.iter_rows():
            for cell in row:
                cell.font = font

    print(f"数据已转换为Excel文件: {output_file}")
    print(f"共导出 {len(services_data)} 个服务")


def convert_multiple_json_to_excel(json_files: List[str], output_file: str):
    """将多个JSON文件转换为一个Excel文件的多个sheet"""
    if not json_files:
        print("没有找到JSON文件")
        return

    total_services = 0

    # 创建Excel写入器
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for json_file in json_files:
            try:
                # 加载数据
                composers_data = load_json_data(json_file)

                # 提取services数据
                services_data = extract_services_data(composers_data)

                if not services_data:
                    print(f"在 {json_file} 中没有找到services数据")
                    continue

                # 获取hostname作为sheet名称
                hostname = (
                    composers_data[0].get("hostname", "Unknown") if composers_data else "Unknown"
                )
                # 清理sheet名称（Excel sheet名称有特殊字符限制）
                sheet_name = (
                    hostname.replace("/", "_").replace("\\", "_").replace(":", "_")[:31]
                )  # Excel sheet名称最大31个字符

                # 创建DataFrame
                df = pd.DataFrame(services_data)

                # 写入到对应的sheet
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 自适应列宽和设置字体
                worksheet = writer.sheets[sheet_name]

                # 设置字体为微软雅黑
                font = Font(name="微软雅黑", size=10)

                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter

                    for cell in column:
                        # 设置字体
                        cell.font = font

                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass

                    # 设置列宽，最小宽度10，最大宽度50
                    adjusted_width = min(max(max_length + 2, 10), 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

                total_services += len(services_data)
                print(f"已处理 {json_file}，主机名: {hostname}，服务数: {len(services_data)}")

            except Exception as e:
                print(f"处理文件 {json_file} 时出错: {e}")
                continue

    print(f"数据已转换为Excel文件: {output_file}")
    print(f"共导出 {total_services} 个服务")


def main(storage_dir: Path = STORAGE_DIR, filename: str = STATS_EXCEL_FILENAME):
    """主函数"""
    # 查找storage目录下的JSON文件
    if not storage_dir.exists():
        return

    json_files = list(storage_dir.glob("*.json"))
    if not json_files:
        print("在storage目录下没有找到JSON文件")
        return

    # 生成输出文件名
    output_file = storage_dir / filename

    # 转换为Excel
    print(f"找到 {len(json_files)} 个JSON文件")
    convert_multiple_json_to_excel([str(jf) for jf in json_files], str(output_file))

    with suppress(Exception):
        os.startfile(output_file)


if __name__ == "__main__":
    main()
