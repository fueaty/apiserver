"""
测试运行脚本
"""

import sys
import subprocess
import os

def run_tests():
    """运行测试用例"""
    print("🚀 开始运行智能体工作流API服务测试...")
    
    # 切换到项目根目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # 运行配置测试
    print("\n📋 运行配置管理测试...")
    result1 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_config.py", "-v"], 
                           capture_output=True, text=True)
    
    # 运行认证测试
    print("\n🔐 运行身份验证测试...")
    result2 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_auth.py", "-v"], 
                           capture_output=True, text=True)
    
    # 运行采集测试
    print("\n🌐 运行采集服务测试...")
    result3 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_collection.py", "-v"], 
                           capture_output=True, text=True)
    
    # 输出测试结果
    print("\n" + "="*60)
    print("📊 测试结果汇总:")
    print("="*60)
    
    tests = [
        ("配置管理", result1),
        ("身份验证", result2),
        ("采集服务", result3)
    ]
    
    total_passed = 0
    total_failed = 0
    
    for test_name, result in tests:
        if result.returncode == 0:
            print(f"✅ {test_name}: 通过")
            total_passed += 1
        else:
            print(f"❌ {test_name}: 失败")
            print(f"   错误信息: {result.stderr}")
            total_failed += 1
    
    print("\n" + "="*60)
    print(f"🎯 总体结果: {total_passed} 通过, {total_failed} 失败")
    
    if total_failed == 0:
        print("🎉 所有测试通过！项目功能正常。")
    else:
        print("⚠️  部分测试失败，请检查相关功能。")
    
    print("="*60)
    
    return total_failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)