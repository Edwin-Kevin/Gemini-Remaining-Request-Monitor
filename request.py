# 1. 安装库: pip install google-cloud-service-usage google-cloud-monitoring

from google.cloud import service_usage_v1
from google.cloud.service_usage_v1.types import GetServiceRequest
import google.api_core.exceptions

def get_quota_limit(project_id: str, service_name: str, quota_metric_id: str, target_unit_substring: str, target_model: str = None):
    """
    获取指定 Google Cloud 服务配额的配置限制值，并匹配特定单位子字符串。
    (使用 'in' 检查单位)
    Args:
        project_id: 您的 Google Cloud 项目 ID。
        service_name: 您要查询的服务名称 (例如 'generativelanguage.googleapis.com')。
        quota_metric_id: 您要查询的具体配额指标 ID。
        target_unit_substring: 您期望单位中包含的子字符串 (例如 '/d/' 代表每天)。
        target_model: (可选) 如果配额是按模型区分的，指定目标模型名称 (例如 'gemini-2.0-pro-exp')。
    Returns:
        配额的限制值 (int 或 float)，如果找不到则返回 None。
    """
    client = service_usage_v1.ServiceUsageClient()
    resource_name = f"projects/{project_id}/services/{service_name}"
    try:
        request = GetServiceRequest(name=resource_name)
        service = client.get_service(request=request)
        print(f"成功获取服务配置信息: {service.name}")
        if not service.config or not service.config.quota:
            print("错误：服务配置中未找到配额信息。")
            return None
        limit_value = None
        found_limit_entry = None
        # print("\n--- 开始遍历 service.config.quota.limits ---")
        for i, limit in enumerate(service.config.quota.limits):
            # print(f"\n[{i}] 检查限制条目:")
            current_metric = limit.metric
            current_unit = limit.unit
            # print(f"  Name: {limit.name}")
            # print(f"  Metric: {repr(current_metric)}")
            # print(f"  Unit: {repr(current_unit)}")
            # print(f"  目标 Metric ID: {repr(quota_metric_id)}")
            # print(f"  目标 Unit 子字符串: {repr(target_unit_substring)}") # 注意这里是子字符串
            # 进行比较
            metric_matches = (current_metric == quota_metric_id)
            # 检查单位是否包含目标子字符串
            unit_matches = isinstance(current_unit, str) and (target_unit_substring in current_unit) # <--- 修改在这里
            # print(f"  指标是否匹配? {metric_matches}")
            # print(f"  单位是否匹配 (包含 '{target_unit_substring}')? {unit_matches}") # 修改打印信息
            if metric_matches and unit_matches:
                found_limit_entry = limit
                # print(f"  >>> 找到完全匹配! <<<")
                break
            else:
        #         print(f"  --- 此条目不完全匹配 ---")
                continue
        # print("--- 遍历结束 ---")
        if not found_limit_entry:
            # 修改错误信息以反映新的逻辑
            print(f"错误：在服务 {service_name} 的配置中未找到指标为 '{quota_metric_id}' 且单位包含 '{target_unit_substring}' 的配额。")
            # ... (打印可用指标的代码保持不变) ...
            return None
        # --- 从找到的 limit 条目中提取值的逻辑保持不变 ---
        target_key = f"DEFAULT/{{model={target_model}}}" if target_model else "DEFAULT"
        specific_value_found = False
        if target_model and target_key in found_limit_entry.values:
            value_str = found_limit_entry.values[target_key]
            try:
                limit_value = int(value_str) if value_str != "-1" else float('inf')
                specific_value_found = True
                print(f"  找到模型 '{target_model}' 的特定限制值: {'无限' if limit_value == float('inf') else limit_value}")
            except ValueError:
                 print(f"  错误：无法将模型 '{target_model}' 的限制值 '{value_str}' 转换为数字。")
                 return None
        elif "DEFAULT" in found_limit_entry.values:
            if not specific_value_found:
                 value_str = found_limit_entry.values["DEFAULT"]
                 try:
                     limit_value = int(value_str) if value_str != "-1" else float('inf')
                     print(f"  使用默认限制值: {'无限' if limit_value == float('inf') else limit_value}")
                 except ValueError:
                      print(f"  错误：无法将默认限制值 '{value_str}' 转换为数字。")
                      return None
        else:
            print(f"  警告：指标 {quota_metric_id} (单位: {found_limit_entry.unit}) 既没有找到模型 '{target_model}' 的特定值，也没有找到 DEFAULT 值。")
            return None
        return limit_value
    # --- 异常处理保持不变 ---
    except google.api_core.exceptions.NotFound:
        print(f"错误：找不到服务 {service_name} 或项目 {project_id}。请确保服务已启用且项目ID正确。")
        return None
    except google.api_core.exceptions.PermissionDenied:
        print(f"错误：权限不足。请确保运行此代码的凭据具有访问 Service Usage API 的权限 (例如 'Service Usage Consumer' 角色)。")
        return None
    except Exception as e:
        print(f"获取配额限制时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None

from google.cloud import monitoring_v3
import time
from google.protobuf import field_mask_pb2
import datetime
import pytz # 用于处理时区
def get_realtime_quota_usage(project_id: str, quota_metric_id: str, target_model: str = None, time_window_hours: int = 24):
    """
    使用 Cloud Monitoring API 获取配额在指定时间窗口内的累计用量。
    Args:
        project_id: 您的 Google Cloud 项目 ID (例如 'gen-lang-client-0161950435')。
        quota_metric_id: 您要查询的配额指标 ID (例如 'generativelanguage.googleapis.com/generate_content_free_tier_requests')。
        target_model: (可选) 如果配额是按模型区分的，指定目标模型名称。
        time_window_hours: 查询过去多少小时的累计用量 (默认为 24 小时，适用于每日配额)。
    Returns:
        时间窗口内的累计用量值 (float)，如果获取失败则返回 None。
    """
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    # 对于每日配额，通常使用 allocation/usage 指标类型
    metric_type = f"serviceruntime.googleapis.com/quota/allocation/usage"
    # 构建过滤器
    filter_string = f'metric.type="{metric_type}" resource.type="consumer_quota" metric.label.quota_metric="{quota_metric_id}"'
    # 模型过滤 (仍然需要确认标签键名!)
    model_label_key = "resource.label.model_id" # <--- 确认或修改这里!
    if target_model:
        filter_string += f' {model_label_key}="{target_model}"'
    # 设置查询时间范围 (查询过去 N 小时)
    now = time.time()
    seconds = int(now)
    nanos = int((now - seconds) * 10**9)
    start_seconds = seconds - (time_window_hours * 3600)
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": seconds, "nanos": nanos},
            "start_time": {"seconds": start_seconds, "nanos": 0}, # 从 N 小时前开始
        }
    )
    # 对于每日配额，我们通常关心的是时间窗口内的 *总和* 或 *最新值*
    # 如果是 allocation/usage，它本身可能就是累计值，取最新点即可。
    # 如果是 rate/net_usage，则需要聚合 (Aggregation) 求和。
    # 由于我们用了 allocation/usage，先尝试直接取最新点。
    print(f"\n正在使用 Cloud Monitoring 查询实时用量...")
    print(f"Filter: {filter_string}")
    print(f"Time Interval: last {time_window_hours} hours")
    try:
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": filter_string,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                # 如果需要聚合（例如对 rate 指标求和），在这里添加 aggregation
                # "aggregation": {
                #     "alignment_period": {"seconds": 86400}, # 对齐周期，例如一天
                #     "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_SUM, # 或 ALIGN_DELTA
                #     "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
                #     "group_by_fields": ["metric.label.quota_metric", model_label_key] # 按需要的标签分组
                # }
            }
        )
        # 处理返回的时间序列数据
        usage_value = 0.0 # 默认用量为0
        point_count = 0
        series_count = 0
        latest_point_time = 0
        for series in results:
            series_count += 1
            # print(f"找到时间序列: {series}") # 调试用
            if series.points:
                # allocation/usage 通常是递增的，取最新的点代表当前累计值
                point = series.points[0] # 最新点在前面
                point_time = point.interval.end_time.seconds
                point_count += 1
                # 如果有多个序列（不应该发生，除非过滤器不精确），取最新的那个点
                if point_time > latest_point_time:
                    latest_point_time = point_time
                    if point.value.type_ == monitoring_v3.TypedValue.ValueType.INT64:
                        usage_value = float(point.value.int64_value)
                        print(f"  找到用量数据点 (int64, time: {datetime.datetime.fromtimestamp(point_time)}): {usage_value}")
                    elif point.value.type_ == monitoring_v3.TypedValue.ValueType.DOUBLE:
                        usage_value = point.value.double_value
                        print(f"  找到用量数据点 (double, time: {datetime.datetime.fromtimestamp(point_time)}): {usage_value}")
                    else:
                        print(f"  找到数据点，但值类型未知: {point.value.type_}")
            else:
                 print("  找到时间序列，但没有数据点。")
        if series_count == 0:
             print("警告：Cloud Monitoring 未返回与过滤器匹配的时间序列数据。用量可能为0，或者��滤器/指标名称/标签不正确。")
             return 0.0 # 返回 0 表示未检测到用量
        elif point_count == 0 and series_count > 0:
             print("警告：找到了时间序列，但在指定时间窗口内没有数据点。用量可能为0。")
             return 0.0 # 返回 0 表示未检测到用量
        elif series_count > 1:
             print(f"警告：Cloud Monitoring 返回了 {series_count} 个时间序列，可能过滤器不够精确。已使用最新时间戳的数据点。")
        # 注意：这个值是 *当前时间点* 的累计用量（自上次重置以来）。
        # 对于严格的“今天”用量，可能需要更复杂的逻辑（例如查询两次，取差值，或使用更精确的时间窗口对齐到天的开始）。
        # 但对于监控剩余量，这个最新的累计值通常足够。
        return usage_value
    except google.api_core.exceptions.PermissionDenied as e:
        print(f"Error msg: {e}")
        print(f"错误：权限不足。请确保运行此代码的凭据具有访问 Cloud Monitoring API 的权限 (例如 'Monitoring Viewer' 角色)。")
        return None
    except Exception as e:
        print(f"查询 Cloud Monitoring 时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None


# --- 使用示例 ---
if __name__ == "__main__":
    project_id = "gen-lang-client-0161950435"
    service_name = "generativelanguage.googleapis.com"
    # 使用从 Service Config 中找到的 Metric ID
    quota_metric_id_to_check = "generativelanguage.googleapis.com/generate_content_free_tier_requests"
    # 指定您关心的模型
    target_model_name = "gemini-2.0-pro-exp" # <--- 您关心的模型
    target_unit_sub = "/d"

    print(f"--- 步骤 1: 获取配额限制值 ---")
    limit = get_quota_limit(project_id, service_name, quota_metric_id_to_check, target_unit_sub, target_model_name)

    if limit is not None:
        # 检查是否为无限大
        is_unlimited = (limit == float('inf'))
        limit_display = "无限" if is_unlimited else int(limit) # 显示时取整

        # print(f"\n成功获取到配额 '{quota_metric_id_to_check}' (模型: {target_model_name}), 单位: {target_unit_sub} 的限制值: {limit_display}")

        if is_unlimited:
             print("\n配额无限制，无需查询用量。")
             print(f"\n--- 结果 ---")
             print(f"配额指标: {quota_metric_id_to_check}")
             print(f"模型: {target_model_name}")
             print(f"限制 (Limit): 无限")
             print(f"当前用量 (Usage): N/A")
             print(f"剩余 (Remaining): 无限")
        else:
            print(f"\n--- 步骤 2: 获取实时用量 (使用 Cloud Monitoring, 过去 24 小时) ---")
            # 注意：这里需要确保 Cloud Monitoring API 已启用，并且凭据有权限
            # 对于每日配额，查询过去 24 小时的累计用量
            usage = get_realtime_quota_usage(project_id, quota_metric_id_to_check, target_model_name, time_window_hours=24)
            if usage is not None:
                print(f"\n成功获取到过去 24 小时累计用量: {usage}")
                remaining = limit - usage
                print(f"\n--- 结果 ---")
                print(f"配额指标: {quota_metric_id_to_check}")
                print(f"模型: {target_model_name}")
                print(f"每日限制 (Limit): {limit_display}")
                print(f"当前用量 (Usage in last 24h): {usage:.2f}") # 显示两位小数
                print(f"剩余 (Remaining): {remaining:.2f}")
            else:
                print("\n未能获取实时用量。无法计算剩余量。")
                print(f"\n--- 结果 (仅限制值) ---")
                print(f"配额指标: {quota_metric_id_to_check}")
                print(f"模型: {target_model_name}")
                print(f"每日限制 (Limit): {limit_display}")
                print(f"当前用量 (Usage): 未知")
                print(f"剩余 (Remaining): 未知")
    else:
        print("\n未能获取配额限制值。请检查之前的错误信息。")
    print("\n脚本执行完毕。")
