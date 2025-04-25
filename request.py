# TODO: 使用系统代理

# 1. 安装库: pip install google-cloud-service-usage

from google.cloud import service_usage_v1
from google.cloud.service_usage_v1.types import GetServiceRequest # 导入请求类型
import google.api_core.exceptions

def get_quota_usage(project_id: str, service_name: str, quota_metric_id: str):
    """
    获取指定 Google Cloud 服务配额的当前用量和限制。

    Args:
        project_id: 您的 Google Cloud 项目 ID。
        service_name: 您要查询的服务名称 (例如 'generativelanguage.googleapis.com')。
        quota_metric_id: 您要查询的具体配额指标 ID。

    Returns:
        一个包含限制值、当前用量和剩余用量的字典，如果找不到配额则返回 None。
    """
    client = service_usage_v1.ServiceUsageClient()

    # 构建资源名称
    # 格式通常是 projects/{project_number}/services/{service_name}
    # 或者 projects/{project_id}/services/{service_name}
    # Service Usage API 通常需要 project number，但 client 库可能允许 project_id
    # 如果使用 project_id 不行，请尝试获取 project number
    # 您可以在 gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)' 获取
    resource_name  = f"projects/{project_id}/services/{service_name}"

    try:
        # 创建 GetServiceRequest 对象
        request = GetServiceRequest(name=resource_name) # 将 name 设置给请求对象

        # 获取服务信息，主要为了拿到 consumerQuotaMetrics
        service = client.get_service(request=request)
        print(f"成功获取服务信息: {service.name}")

        # 查找特定的配额指标
        target_quota = None
        for metric in service.consumer_quota_metrics:
            # 指标名称通常在 metric.name 中，但我们需要匹配的是 limit 下的 metric
            # 或者直接在 metric 的 display_name 或 metric 字段查找
            # print(f"检查指标: {metric.name}, 显示名称: {metric.display_name}")
            # 遍历该指标下的所有限制
            for limit in metric.consumer_quota_limits:
                 # print(f" - 检查限制单元: {limit.quota_unit}, 指标: {limit.metric}")
                 # 配额指标ID通常在 limit.metric 字段
                 if limit.metric == quota_metric_id:
                     target_quota = metric
                     target_limit_unit = limit.quota_unit # 找到匹配的限制单元
                     print(f"找到目标配额指标: {quota_metric_id}")
                     break
            if target_quota:
                break

        if not target_quota:
            print(f"错误：在服务 {service_name} 中未找到配额指标 {quota_metric_id}")
            return None

        # 获取该配额指标的当前用量
        # 注意：consumer_quota_metrics 返回的是配置信息，不直接包含实时用量
        # 需要使用 list_consumer_quota_metrics 并查找特定 limit 的 value
        # 或者更直接的方式是依赖 Cloud Monitoring API 获取实时用量，
        # 但 Service Usage API *应该* 能提供一些信息，我们先尝试从 limit value 获取

        current_usage = -1 # 默认值表示未获取到
        limit_value = -1   # 默认值

        # 重新遍历找到的 target_quota 的 limits 来获取值
        for limit in target_quota.consumer_quota_limits:
            if limit.quota_unit == target_limit_unit: # 确保是我们找到的那个limit
                # limit_value 通常在 quota_buckets[0].effective_limit 中
                if limit.quota_buckets:
                    limit_value = limit.quota_buckets[0].effective_limit
                    # 当前用量没有直接字段，需要通过 Cloud Monitoring 获取
                    # 这里我们暂时无法通过 Service Usage API 直接获取实时用量
                    # 您需要结合 Cloud Monitoring API 来获取 'serviceruntime.googleapis.com/quota/allocation/usage'
                    # 或类似指标的值，并按 quota_metric_id 过滤
                    print(f"警告：Service Usage API 可能不直接提供实时用量。")
                    print(f"配额限制值: {limit_value}")
                    # 暂时将当前用量设为未知
                    current_usage = "未知 (需使用 Monitoring API)"
                    break

        if limit_value == -1:
             print(f"错误：未能找到 {quota_metric_id} 的限制值。")
             return None

        # 计算剩余量 (如果能获取到当前用量)
        remaining = "未知"
        if isinstance(current_usage, (int, float)) and isinstance(limit_value, (int, float)):
             remaining = limit_value - current_usage

        return {
            "limit": limit_value,
            "usage": current_usage,
            "remaining": remaining,
            "quota_metric_id": quota_metric_id
        }

    except google.api_core.exceptions.NotFound:
        print(f"错误：找不到服务 {service_name} 或项目 {project_id}")
        return None
    except Exception as e:
        print(f"获取配额时发生错误: {e}")
        return None

# --- 使用示例 ---
if __name__ == "__main__":
    project_id = "gen-lang-client-0161950435"  # 替换为您的项目 ID
    service_name = "generativelanguage.googleapis.com"
    # !! 重要：替换为你要查询的准确配额指标 ID !!
    # 这只是一个猜测的示例ID，你需要找到正确的那个
    quota_metric_id_to_check = "generativelanguage.googleapis.com/generate_content_free_tier_requests" # <--- 修改这里

    quota_info = get_quota_usage(project_id, service_name, quota_metric_id_to_check)

    if quota_info:
        print("\n--- 配额信息 ---")
        print(f"  指标 ID: {quota_info['quota_metric_id']}")
        print(f"  限制值 ({quota_info['quota_unit']}): {quota_info['limit']}")
        print(f"  当前用量: {quota_info['usage']}")
        print(f"  剩余量: {quota_info['remaining']}")
        print("\n注意：当前用量可能需要通过 Cloud Monitoring API 获取以获得实时数据。")
    else:
        print("\n未能获取配额信息。请仔细检查:")
        print(f"  1. 项目ID '{project_id}' 是否正确?")
        print(f"  2. 服务名称 '{service_name}' 是否正确且已在项目中启用?")
        print(f"  3. 配额指标ID '{quota_metric_id_to_check}' 是否是该服务下真实存在的指标ID?")
        print(f"  4. 运行环境是否已正确配置 Google Cloud 认证凭据并拥有足够权限?")
        print(f"  5. 如果指标ID错误，请参考上面代码注释中的方法查找正确的ID。")
