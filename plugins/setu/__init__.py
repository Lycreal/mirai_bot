import asyncio
import random
import re
from typing import List, Set, Union

from mirai import Mirai, Group, GroupMessage, Image, Plain
from mirai.event.message.chain import Source
from mirai.logger import Event as EventLogger

from .SetuData import SetuData, SetuResp, SetuDatabase
from .utils import CoolDown, shuzi2number

cd = CoolDown(app='setu', td=20)

sub_app = Mirai(f"mirai://localhost:8080/?authKey=0&qq=0")


@sub_app.receiver("GroupMessage")
async def GMHandler(app: Mirai, message: GroupMessage):
    match = re.match(r'(?:.*?([\d一二两三四五六七八九十]*)张|来点)?(.{0,10}?)的?色图$', message.toString())
    if match:
        number: int = shuzi2number(match[1])
        if number > 10:
            number = 1
        keyword = match[2]
        try:
            await setuExecutor(app, message, number, keyword)
        except Exception as e:
            import traceback
            EventLogger.error(e)
            EventLogger.error(traceback.format_exc())

    elif message.toString() == '色图配额':
        await checkQuota(app, message)


async def checkQuota(app: Mirai, message: GroupMessage):
    resp = await SetuResp.get('色图配额')
    await app.sendGroupMessage(group=message.sender.group,
                               message=f'剩余配额：{resp.quota}\n恢复时间：{resp.time_to_recover.strftime("%m-%d %H:%M")}',
                               quoteSource=message.messageChain.getSource())


async def setuExecutor(app: Mirai, message: GroupMessage, number: int, keyword: str):
    """根据关键词获取data_array，并调用sendSetu"""
    member_id: int = message.sender.id
    if keyword == '':
        if len(SetuDatabase.load_from_file().__root__) >= 300:
            resp = SetuResp(code=-430, msg='空关键词')
        else:
            resp = await SetuResp.get()
    elif cd.check(member_id):
        resp = await SetuResp.get(keyword)
    else:
        resp = SetuResp(code=-3, msg='你的请求太快了，休息一下吧')

    if resp.code == 0:
        cd.update(member_id)
        await sendSetu(app, message, resp.data, number)
    elif resp.code in [429, -430]:
        db = SetuDatabase.load_from_file()
        await sendSetu(app, message, db.__root__, number)
    else:
        group: Group = message.sender.group
        source: Source = message.messageChain.getSource()
        await app.sendGroupMessage(group, resp.msg, source)


async def sendSetu(app: Mirai, message: GroupMessage, data_array: Union[Set[SetuData], List[SetuData]], number: int):
    """发送data_array"""
    group: Group = message.sender.group
    source: Source = message.messageChain.getSource()

    async def send(_prefix: str, _data: SetuData):
        try:
            setu_b: bytes = await _data.get()
            await app.sendGroupMessage(group,
                                       [Plain(_prefix + _data.purl + '\n'), Image.fromBytes(setu_b)],
                                       source)
            EventLogger.info(f"{_prefix}色图已发送，标签：{','.join(_data.tags)}")
        except asyncio.TimeoutError as e:
            EventLogger.warn('连接超时' + str(e))
            raise e
        except ValueError as e:
            EventLogger.warn('图片尺寸检查失败' + str(e))
            raise e

    number = min(number, len(data_array))

    tasks: List[asyncio.Task] = []
    for i, data in enumerate(random.sample(data_array, k=number)):
        prefix = f'[{i + 1}/{number}]' if number > 1 else ''
        task = asyncio.create_task(send(prefix, data))
        tasks.append(task)
        await asyncio.wait(tasks, timeout=5)
    done, pending = await asyncio.wait(tasks, timeout=10)
    num_exception = len([task for task in done if task.exception()])
    num_pending = len([t.cancel() for t in pending])
    if num_exception or num_pending:
        msg = f'{number}个任务中，{num_pending}个超时，{num_exception}个异常。'
        await app.sendGroupMessage(group, msg, source)
