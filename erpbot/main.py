import asyncio
from functools import partial
from .bootstrap import initialize_runtime
from .core import runtime
from .loader import register_handlers


def _get_schedulers():
    from .scheduler.jobs import background_schedulers
    from .scheduler.reminders import run_scheduler
    runtime.require_initialized()
    return (partial(background_schedulers, runtime.get_connection, runtime.bot,
                    runtime.get_current_tehran_time, runtime.DB_PATH),
            partial(run_scheduler, runtime.get_connection, runtime.bot, runtime.get_current_tehran_time))

async def main():
    application = initialize_runtime()
    tasks = []
    try:
        runtime.init_db()
        register_handlers()
        for scheduler in _get_schedulers():
            tasks.append(asyncio.create_task(scheduler()))
        await application.dispatcher.start_polling(application.bot, close_bot_session=False)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await application.close()

if __name__ == "__main__":
    asyncio.run(main())
