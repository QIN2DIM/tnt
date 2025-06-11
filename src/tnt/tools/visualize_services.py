"""
简化的服务依赖关系可视化工具
使用Pyvis生成简单的网络图，展示Docker Compose服务和代理依赖
支持将多个主机的数据合并到同一张画布上，展示局域网内的代理共享情况
"""

import json
import os
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Dict, List

from pyvis.network import Network
from rich.console import Console
from rich.table import Table

from tnt.tools.constant import STORAGE_DIR, STATS_VIS_FILENAME

console = Console()


class ServiceVisualizer:
    """简化的服务依赖关系可视化器"""

    def __init__(self):
        self.net = None
        self.service_proxy_map = defaultdict(set)  # 服务到代理的映射
        self.proxy_usage_stats = defaultdict(
            lambda: {"hosts": set(), "services": set()}
        )  # 代理使用统计
        self.proxy_positions = {}  # 代理节点的固定位置

    def extract_proxy_info(self, services: List[Dict], hostname: str) -> Dict[str, Dict]:
        """从服务环境变量中提取代理信息

        返回: {proxy_url: {'services': set(), 'details': {...}}}
        """
        proxy_info = defaultdict(lambda: {"services": set(), "details": {}})

        for service in services:
            service_name = service.get("name", "")
            env_vars = service.get("container_env", [])

            for env_var in env_vars:
                if "=" in env_var:
                    key, value = env_var.split("=", 1)
                    # 检查是否是代理相关的环境变量
                    if "proxy" in key.lower() and value.lower().startswith("http://"):
                        proxy_info[value]["services"].add(service_name)
                        proxy_info[value]["details"][key] = value
                        self.service_proxy_map[service_name].add(value)
                        # 记录代理使用统计
                        self.proxy_usage_stats[value]["hosts"].add(hostname)
                        self.proxy_usage_stats[value]["services"].add(f"{hostname}:{service_name}")

        return proxy_info

    def build_network(self, data: List[Dict], is_merged: bool = False):
        """构建简化的网络图

        Args:
            data: 服务数据列表
            is_merged: 是否为合并模式（多个主机）
        """
        # 初始化网络，使用更大的画布和固定布局
        self.net = Network(
            height="1200px", width="100%", bgcolor="#f5f5f5", font_color="#333333", directed=True
        )

        # 使用固定布局，禁用物理引擎
        self.net.set_options(
            """
        var options = {
            "physics": {
                "enabled": false
            },
            "edges": {
                "arrows": {
                    "to": {
                        "enabled": true,
                        "scaleFactor": 0.8
                    }
                },
                "color": {
                    "color": "#666666",
                    "highlight": "#ff0000"
                },
                "smooth": {
                    "type": "curvedCW",
                    "roundness": 0.1
                }
            },
            "nodes": {
                "font": {
                    "size": 14,
                    "face": "Arial"
                }
            },
            "interaction": {
                "hover": true,
                "tooltipDelay": 200
            }
        }
        """
        )

        # 首先收集所有代理信息
        all_proxy_info = defaultdict(lambda: {"services": set(), "details": {}})

        for composer_data in data:
            hostname = composer_data.get("hostname", "unknown")
            services = composer_data.get("services", [])
            proxy_info = self.extract_proxy_info(services, hostname)

            for proxy_url, info in proxy_info.items():
                all_proxy_info[proxy_url]["services"].update(info["services"])
                all_proxy_info[proxy_url]["details"].update(info["details"])

        # 计算布局
        proxy_count = len(all_proxy_info)
        if proxy_count > 0:
            # 代理节点在顶部横向排列
            proxy_spacing = 1200 / (proxy_count + 1)
            for i, proxy_url in enumerate(sorted(all_proxy_info.keys())):
                x = (i + 1) * proxy_spacing - 600
                y = -400  # 顶部位置
                self.proxy_positions[proxy_url] = (x, y)

        # 添加代理节点（置顶）
        self._add_proxy_nodes_pinned(all_proxy_info, is_merged)

        # 添加主机、服务等节点
        host_count = len(set(d.get("hostname", "unknown") for d in data))
        host_spacing = 1200 / (host_count + 1) if host_count > 0 else 600
        host_index = 0

        for composer_data in data:
            hostname = composer_data.get("hostname", "unknown")

            # 计算主机位置
            host_x = (host_index + 1) * host_spacing - 600
            host_y = 0

            # 添加主机节点
            self.net.add_node(
                hostname,
                label=hostname,
                color="#2196F3",
                x=host_x,
                y=host_y,
                size=30,
                shape="box",
                font={"size": 16, "color": "white"},
                title=f"主机: {hostname}",
            )

            # 添加Compose项目和服务
            composer_name = composer_data.get("name", "")
            composer_id = f"{hostname}_{composer_name}"

            # Compose项目位置
            self.net.add_node(
                composer_id,
                label=composer_name,
                color="#4CAF50",
                x=host_x,
                y=host_y + 150,
                size=25,
                shape="box",
                title=f"Docker Compose: {composer_name}",
            )

            # 连接主机到Compose项目
            self.net.add_edge(hostname, composer_id, color="#cccccc", width=1)

            # 添加服务节点
            services = composer_data.get("services", [])
            service_count = len(services)
            if service_count > 0:
                service_spacing = 200 / (service_count + 1) if service_count > 1 else 0

                for j, service in enumerate(services):
                    service_name = service.get("name", "")
                    service_id = f"{composer_id}_{service_name}"

                    # 计算服务位置
                    service_x = host_x + (j - service_count / 2 + 0.5) * service_spacing
                    service_y = host_y + 300

                    # 服务颜色
                    color = "#FFA726" if service.get("is_depend_on_gpu") else "#66BB6A"

                    self.net.add_node(
                        service_id,
                        label=service_name,
                        color=color,
                        x=service_x,
                        y=service_y,
                        size=20,
                        shape="dot",
                        title=f"服务: {service_name}\n镜像: {service.get('image', 'N/A')}",
                    )

                    # 连接Compose项目到服务
                    self.net.add_edge(composer_id, service_id, color="#cccccc", width=1)

                    # 连接服务到代理
                    self._connect_service_to_proxies(
                        service_id, service_name, hostname, all_proxy_info
                    )

            host_index += 1

    def _add_proxy_nodes_pinned(self, proxy_info: Dict[str, Dict], is_merged: bool = False):
        """添加固定位置的代理节点"""
        from collections import defaultdict

        for proxy_url, (x, y) in self.proxy_positions.items():
            info = proxy_info[proxy_url]
            proxy_id = f"proxy_{proxy_url}"
            display_name = proxy_url.replace("http://", "").split(":")[0]

            # 获取使用统计
            usage_stats = self.proxy_usage_stats.get(proxy_url, {"hosts": set(), "services": set()})

            # 简洁的标签
            is_shared = is_merged and len(usage_stats["hosts"]) > 1
            label = f"{display_name}\n({len(usage_stats['services'])} 服务)"

            # 构建详细的提示信息 - 包含完整的服务依赖列表
            proxy_details = []
            proxy_details.append(f"🔗 代理服务器: {proxy_url}")
            proxy_details.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            proxy_details.append(f"📊 使用统计:")
            proxy_details.append(f"  • 主机数量: {len(usage_stats['hosts'])}")
            proxy_details.append(f"  • 服务总数: {len(usage_stats['services'])}")
            proxy_details.append(f"  • 跨主机共享: {'是' if is_shared else '否'}")

            proxy_details.append(f"\n📋 使用此代理的服务详情:")

            # 按主机分组显示服务
            host_services = defaultdict(list)
            for service_full in sorted(usage_stats["services"]):
                if ":" in service_full:
                    host, service = service_full.split(":", 1)
                    host_services[host].append(service)

            for host in sorted(host_services.keys()):
                proxy_details.append(f"\n  🖥️ {host}:")
                for service in sorted(host_services[host]):
                    proxy_details.append(f"    • {service}")

            # 添加环境变量配置
            if info["details"]:
                proxy_details.append(f"\n⚙️ 环境变量配置:")
                for env_key in sorted(info["details"].keys()):
                    proxy_details.append(f"  • {env_key}")

            title = "\n".join(proxy_details)

            # 添加代理节点 - 使用醒目的颜色
            self.net.add_node(
                proxy_id,
                label=label,
                color="#E91E63" if is_shared else "#9C27B0",
                x=x,
                y=y,
                size=40,
                shape="star",
                font={"size": 16, "color": "white", "bold": True},
                title=title,
                physics=False,  # 确保位置固定
            )

    def _connect_service_to_proxies(
        self, service_id: str, service_name: str, hostname: str, proxy_info: Dict[str, Dict]
    ):
        """连接服务到其使用的代理"""
        service_key = f"{hostname}:{service_name}"

        for proxy_url, info in proxy_info.items():
            usage_stats = self.proxy_usage_stats.get(proxy_url, {"hosts": set(), "services": set()})
            if service_key in usage_stats["services"]:
                proxy_id = f"proxy_{proxy_url}"
                # 使用醒目的红色连线表示代理依赖
                self.net.add_edge(
                    service_id,
                    proxy_id,
                    color="#F44336",
                    width=2,
                    dashes=False,
                    title=f"使用代理: {proxy_url}",
                )

    def generate_summary_table(self) -> Table:
        """生成代理使用摘要表格"""
        table = Table(title="代理使用摘要", show_header=True, header_style="bold magenta")
        table.add_column("代理地址", style="cyan", no_wrap=True)
        table.add_column("主机数", justify="center", style="green")
        table.add_column("服务数", justify="center", style="green")
        table.add_column("跨主机共享", justify="center", style="yellow")
        table.add_column("使用的主机", style="dim")

        for proxy_url, stats in sorted(self.proxy_usage_stats.items()):
            is_shared = len(stats["hosts"]) > 1
            hosts_str = ", ".join(sorted(stats["hosts"])[:3])
            if len(stats["hosts"]) > 3:
                hosts_str += f" ... (+{len(stats['hosts']) - 3})"

            table.add_row(
                proxy_url,
                str(len(stats["hosts"])),
                str(len(stats["services"])),
                "✓" if is_shared else "✗",
                hosts_str,
            )

        return table

    def save_visualization(self, output_file: str = "service_network.html"):
        """保存可视化结果，并添加自定义样式"""
        if self.net:
            # 先生成基础HTML
            self.net.save_graph(output_file)

            # 读取并修改HTML，添加自定义样式和说明
            with open(output_file, "r", encoding="utf-8") as f:
                html_content = f.read()

            # 生成统计信息HTML
            stats_html = self._generate_stats_html()

            # 添加自定义样式和说明面板
            custom_style = """
            <style>
                body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
                #mynetwork { height: 100vh; }
                .info-panel {
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    background: white;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    font-size: 14px;
                    max-width: 350px;
                    max-height: 90vh;
                    overflow-y: auto;
                }
                .info-panel h3 { margin-top: 0; color: #333; }
                .legend-item { margin: 5px 0; }
                .legend-color {
                    display: inline-block;
                    width: 20px;
                    height: 20px;
                    margin-right: 8px;
                    vertical-align: middle;
                    border-radius: 3px;
                }
                .stats-section {
                    margin-top: 15px;
                    padding-top: 15px;
                    border-top: 1px solid #eee;
                }
                .stats-table {
                    width: 100%;
                    font-size: 12px;
                    border-collapse: collapse;
                    margin-top: 10px;
                }
                .stats-table th {
                    background: #f0f0f0;
                    padding: 5px;
                    text-align: left;
                    font-weight: bold;
                    border-bottom: 1px solid #ddd;
                }
                .stats-table td {
                    padding: 5px;
                    border-bottom: 1px solid #eee;
                }
                .shared-proxy {
                    color: #E91E63;
                    font-weight: bold;
                }
                .proxy-details {
                    font-size: 11px;
                    color: #666;
                    margin-left: 10px;
                }
            </style>
            """

            info_panel = f"""
            <div class="info-panel">
                <h3>🎯 代理网络拓扑图</h3>
                <div class="legend-item">
                    <span class="legend-color" style="background: #E91E63;"></span>
                    <span>共享代理（多主机）</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #9C27B0;"></span>
                    <span>独占代理（单主机）</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #2196F3;"></span>
                    <span>主机</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #4CAF50;"></span>
                    <span>Docker Compose</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #FFA726;"></span>
                    <span>GPU服务</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #66BB6A;"></span>
                    <span>普通服务</span>
                </div>
                
                {stats_html}
                
                <hr style="margin: 15px 0;">
                <p style="margin: 5px 0; color: #666; font-size: 12px;">
                    <strong>💡 使用提示：</strong><br>
                    • 代理节点固定在顶部<br>
                    • 红色连线表示代理依赖<br>
                    • 鼠标悬停查看详细信息<br>
                    • 可拖拽和缩放视图
                </p>
            </div>
            """

            # 在</head>标签前插入自定义样式
            html_content = html_content.replace("</head>", custom_style + "</head>")

            # 在<body>标签后插入信息面板
            html_content = html_content.replace("<body>", "<body>" + info_panel)

            # 写回文件
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)

            console.print(f"[green]✅ 可视化结果已保存到: {output_file}[/green]")
        else:
            console.print("[red]❌ 网络图未构建[/red]")

    def _generate_stats_html(self) -> str:
        """生成统计信息的HTML内容"""
        if not self.proxy_usage_stats:
            return ""

        # 计算统计数据
        total_proxies = len(self.proxy_usage_stats)
        shared_proxies = sum(
            1 for stats in self.proxy_usage_stats.values() if len(stats["hosts"]) > 1
        )
        total_services = sum(len(stats["services"]) for stats in self.proxy_usage_stats.values())
        unique_hosts = set()
        for stats in self.proxy_usage_stats.values():
            unique_hosts.update(stats["hosts"])

        stats_html = f"""
        <div class="stats-section">
            <h4>📊 统计信息</h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
                <div>
                    <strong>代理总数:</strong> {total_proxies}<br>
                    <strong>共享代理:</strong> <span class="shared-proxy">{shared_proxies}</span>
                </div>
                <div>
                    <strong>主机总数:</strong> {len(unique_hosts)}<br>
                    <strong>服务总数:</strong> {total_services}
                </div>
            </div>
            
            <h4>🔗 代理使用详情</h4>
            <table class="stats-table">
                <thead>
                    <tr>
                        <th>代理</th>
                        <th>主机</th>
                        <th>服务</th>
                    </tr>
                </thead>
                <tbody>
        """

        # 按共享程度排序（共享的代理排在前面）
        sorted_proxies = sorted(
            self.proxy_usage_stats.items(),
            key=lambda x: (len(x[1]["hosts"]), len(x[1]["services"])),
            reverse=True,
        )

        for proxy_url, stats in sorted_proxies:
            is_shared = len(stats["hosts"]) > 1
            proxy_display = proxy_url.replace("http://", "").split(":")[0]

            # 获取服务列表
            host_services = defaultdict(list)
            for service_full in stats["services"]:
                if ":" in service_full:
                    host, service = service_full.split(":", 1)
                    host_services[host].append(service)

            # 生成服务详情
            services_detail = []
            for host in sorted(host_services.keys()):
                services_detail.append(f"{host}: {', '.join(sorted(host_services[host]))}")

            row_class = "shared-proxy" if is_shared else ""
            stats_html += f"""
                <tr>
                    <td class="{row_class}">{proxy_display}</td>
                    <td>{len(stats['hosts'])}</td>
                    <td>{len(stats['services'])}</td>
                </tr>
            """

        stats_html += """
                </tbody>
            </table>
        </div>
        """

        return stats_html


def load_json_files(path: Path) -> List[Dict]:
    """加载单个JSON文件或目录下的所有JSON文件"""
    all_data = []

    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_data.extend(data)
                else:
                    all_data.append(data)
        except Exception as e:
            console.print(f"[red]❌ 无法读取JSON文件 {path}: {e}[/red]")

    elif path.is_dir():
        json_files = list(path.glob("*.json"))
        if not json_files:
            console.print(f"[yellow]⚠️ 目录 {path} 中没有找到JSON文件[/yellow]")
            return all_data

        console.print(f"[cyan]📂 找到 {len(json_files)} 个JSON文件[/cyan]")
        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_data.extend(data)
                    else:
                        all_data.append(data)
                console.print(f"  ✓ 加载 {json_file.name}")
            except Exception as e:
                console.print(f"  [red]✗ 无法读取 {json_file.name}: {e}[/red]")

    return all_data


def main(
    path_obj: Path = STORAGE_DIR, merge: bool = True, merged_filename: str = STATS_VIS_FILENAME
):
    """Docker Compose服务依赖关系可视化

    PATH: 输入的JSON文件或包含JSON文件的目录路径

    当输入为目录时，默认会将所有JSON文件合并到同一张画布上，
    以展示整个局域网内的代理共享情况。
    """
    console.print(f"[bold blue]🔍 开始分析服务依赖关系...[/bold blue]")

    # 加载数据
    all_data = load_json_files(path_obj)

    if not all_data:
        console.print("[red]❌ 没有有效的数据可以处理[/red]")
        return

    # 根据是否为目录和merge选项决定处理方式
    if path_obj.is_dir() and merge:
        # 合并模式：所有数据在同一张画布上
        console.print(f"[cyan]🔀 合并模式：将 {len(all_data)} 个数据源合并到同一张画布[/cyan]")

        visualizer = ServiceVisualizer()
        visualizer.build_network(all_data, is_merged=True)

        # 统计信息
        total_hosts = len(set(d.get("hostname", "unknown") for d in all_data))
        total_composers = len(all_data)
        total_services = sum(len(composer.get("services", [])) for composer in all_data)
        shared_proxies = sum(
            1 for stats in visualizer.proxy_usage_stats.values() if len(stats["hosts"]) > 1
        )

        console.print(f"\n[green]📊 统计信息:[/green]")
        console.print(f"  - 主机数: {total_hosts}")
        console.print(f"  - Compose项目数: {total_composers}")
        console.print(f"  - 服务总数: {total_services}")
        console.print(f"  - 代理总数: {len(visualizer.proxy_usage_stats)}")
        console.print(f"  - 共享代理数: {shared_proxies}")

        # 显示代理使用摘要表格
        if visualizer.proxy_usage_stats:
            console.print("\n")
            console.print(visualizer.generate_summary_table())

        output_file = str(path_obj.joinpath(merged_filename))
        visualizer.save_visualization(output_file)

        # 给出更清晰的指引
        console.print(f"\n[bold yellow]📌 重要提示:[/bold yellow]")
        console.print(f"  • 所有代理节点已固定在顶部，便于查看")
        console.print(f"  • 红色连线表示服务对代理的依赖关系")
        console.print(f"  • 共享代理使用星形图标和醒目颜色标注")
        console.print(f"  • 鼠标悬停在节点上可查看详细信息")
        with suppress(Exception):
            os.startfile(output_file)
    else:
        # 分离模式：每个数据源生成独立的画布
        console.print(f"[cyan]📄 分离模式：为每个数据源生成独立的画布[/cyan]")

        for i, composer_data in enumerate(all_data):
            visualizer = ServiceVisualizer()
            visualizer.build_network([composer_data])

            hostname = composer_data.get("hostname", f"unknown_{i}")
            composer_name = composer_data.get("name", f"composer_{i}")
            output_file = str(
                path_obj.parent.joinpath(f"service_network_{hostname}_{composer_name}.html")
            )

            visualizer.save_visualization(output_file)

    console.print(f"\n[bold green]✨ 可视化完成！[/bold green]")


if __name__ == "__main__":
    main()
