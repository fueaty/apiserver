#!/usr/bin/env python3
"""
执行数据采集和导出的脚本
该脚本会先运行collection_pipeline.py进行数据采集，
然后再运行export_today_headlines.py导出今日头条数据。
"""

import subprocess
import sys
import os

sys.path.append("..")
import app.wework.notification_push as notification_push

def run_script(script_name):
    """
    运行指定的Python脚本
    """
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    print(f"🚀 正在运行 {script_name}...")
    
    try:
        # 使用subprocess运行脚本
        result = subprocess.run(
            [sys.executable, script_path], 
            check=True, 
            capture_output=True, 
            text=True
        )
        print(f"✅ {script_name} 运行成功")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 运行 {script_name} 时出错:")
        print(f"返回码: {e.returncode}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"❌ 找不到脚本文件: {script_path}")
        return False
    except Exception as e:
        print(f"❌ 运行 {script_name} 时发生未知错误: {e}")
        return False

def main():
    """
    主函数：依次执行数据采集和数据导出
    """
    msg = ("-" * 60) + "\n" + "开始执行数据采集和导出流程" + "\n" + ("-" * 60)
    notification_push.send_message(msg)
    print(msg)
    
    # 第一步：执行数据采集
    msg = ("-" * 60) + "\n" + "📋 第一步：执行数据采集" + "\n" + ("-" * 60)
    notification_push.send_message(msg)
    print(msg)
    if not run_script("collection_pipeline.py"):
        msg = "❌ 数据采集失败，请检查日志"
        notification_push.send_message(msg)
        print(msg)
        sys.exit(1)
    
    # 第二步：执行数据导出
    msg = ("-" * 60) + "\n" + "📤 第二步：执行数据导出" + "\n" + ("-" * 60)
    notification_push.send_message(msg)
    print(msg)
    if not run_script("export_today_headlines.py"):
        msg = "❌ 数据导出失败，请检查日志"
        notification_push.send_message(msg)
        print(msg)
        sys.exit(1)

    msg = ("-" * 60) + "\n" + "🎉 所有任务执行完成!" + "\n" + ("-" * 60)
    notification_push.send_message(msg)
    print("\n🎉 所有任务执行完成!")

if __name__ == "__main__":
    main()