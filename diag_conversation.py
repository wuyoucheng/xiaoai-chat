"""诊断：云端对话接口现在还能不能取到记录"""
import asyncio
import json
import logging
import ssl
import sys
from time import time

sys.stdout.reconfigure(encoding="utf-8")
ssl._create_default_https_context = ssl._create_unverified_context

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

import config
from miservice import MiAccount, MiNAService
from xiaoai import CONVERSATION_API, file_otp_callback
from miservice.miaccount import UA_MINA


async def main():
    account = MiAccount(None, config.MI_USER, config.MI_PASS, otp_callback=file_otp_callback)
    saved = await account.token_store.load_token()
    print(f"本地 token: {'有' if saved else '无'}")
    if saved:
        print(f"  userId={saved.get('userId')}")
        print(f"  keys={list(saved.keys())}")
        account.token = saved

    ok = await account.login("micoapi")
    print(f"登录结果: {ok}, error={account._login_error}")
    if not ok:
        return

    print(f"登录后 keys={list(account.token.keys())}")

    service = MiNAService(account)
    devices = await service.device_list(master=1)
    print(f"设备数: {len(devices)}")

    for d in devices:
        did = d.get("deviceID", "")
        hw = d.get("hardware", "")
        name = d.get("name", "")
        print(f"\n--- {name} hw={hw} id={did[:10]}...")
        url = CONVERSATION_API.format(hardware=hw, timestamp=int(time() * 1000))
        cookies = {
            "userId": account.token["userId"],
            "serviceToken": account.token["micoapi"][1],
            "deviceId": did,
        }
        try:
            async with account.request(url, cookies=cookies, headers={"User-Agent": UA_MINA}) as r:
                raw = await r.read()
                print(f"  HTTP {r.status}, {len(raw)} bytes")
                text = raw.decode("utf-8", "replace")
                print(f"  原始: {text[:600]}")
                if r.status == 200:
                    data = json.loads(text)
                    print(f"  code={data.get('code')} msg={data.get('message')}")
                    ds = data.get("data")
                    if isinstance(ds, str) and ds:
                        parsed = json.loads(ds)
                        recs = parsed.get("records", [])
                        print(f"  记录数={len(recs)}")
                        for rec in recs[:3]:
                            print(f"    ts={rec.get('time')} q={rec.get('query')!r} a={(rec.get('answer') or '')[:40]!r}")
        except Exception as e:
            print(f"  请求异常: {type(e).__name__}: {e}")


asyncio.run(main())
