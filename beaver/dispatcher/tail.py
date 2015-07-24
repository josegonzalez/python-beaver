# -*- coding: utf-8 -*-
import multiprocessing
import Queue
import signal
import os
import time
import threading

from beaver.config import BeaverConfig
from beaver.runqueue import RunQueue
from beaver.ssh_tunnel import create_ssh_tunnel
from beaver.utils import REOPEN_FILES, setup_custom_logger
from beaver.worker.tail_manager import TailManager
from beaver.stubfactory import StubFactory


def run(args=None):

    logger = setup_custom_logger('beaver', args)
    beaver_config = BeaverConfig(args, logger=logger)
    # so the config file can override the logger
    logger = setup_custom_logger('beaver', args, config=beaver_config)

    if beaver_config.get('logstash_version') not in [0, 1]:
        raise LookupError("Invalid logstash_version")

    queue = multiprocessing.JoinableQueue(beaver_config.get('max_queue_size'))

    manager_proc = None
    ssh_tunnel = create_ssh_tunnel(beaver_config, logger=logger)

    beaverctl = StubFactory.create_beaverctl_server()
    beaverctl_thread = threading.Thread(target=beaverctl.start_service_loop)

    def queue_put(*args):
        """Put args into back of queue, blocking"""
        return queue.put(*args)

    def queue_put_nowait(*args):
        """Put args into back of queue, non-blocking"""
        return queue.put_nowait(*args)

    def cleanup(signalnum, frame):
        """Cleans up resources at the end of execution"""
        if signalnum is not None:
            sig_name = \
                tuple((v) for v, k in signal.__dict__.iteritems() \
                if k == signalnum)[0]
            logger.info('{0} detected'.format(sig_name))
            logger.info('Shutting down. Please wait...')
        else:
            logger.info('Worker process cleanup in progress...')

        try:
            queue_put_nowait(("exit", ()))
        except Queue.Full:
            pass

        if manager_proc is not None:
            try:
                beaverctl.stop_service_loop()
                beaverctl_thread.join()

                manager_proc.terminate()
                manager_proc.join()
            except RuntimeError:
                pass

        if ssh_tunnel is not None:
            logger.info("Closing ssh tunnel...")
            ssh_tunnel.close()

        if signalnum is not None:
            logger.info("Shutdown complete.")
            return os._exit(signalnum)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGQUIT, cleanup)

    def create_queue_consumer():
        """Creates and runs, RunQueue and starts beaverctl"""
        run_queue = RunQueue(queue, beaver_config, logger)
        proc = multiprocessing.Process(target=run_queue.loop)
        beaverctl.set_dispatcher(run_queue)

        if not beaverctl_thread.is_alive():
            beaverctl_thread.start()

        logger.info("Starting queue consumer")
        proc.start()
        return proc

    def create_queue_producer():
        """Creates and runs TailManager queue consumer"""
        manager = TailManager(
            beaver_config=beaver_config,
            queue_consumer_function=create_queue_consumer,
            callback=queue_put,
            logger=logger
        )
        manager.run()

    while 1:

        try:

            if REOPEN_FILES:
                logger.debug("Detected non-linux platform. Files will be reopened for tailing")

            t = time.time()
            while True:
                if manager_proc is None or not manager_proc.is_alive():
                    logger.info('Starting worker...')
                    t = time.time()
                    manager_proc = multiprocessing.Process(target=create_queue_producer)
                    manager_proc.start()
                    logger.info('Working...')
                manager_proc.join(10)

                if beaver_config.get('refresh_worker_process'):
                    if beaver_config.get('refresh_worker_process') < time.time() - t:
                        logger.info('Worker has exceeded refresh limit. Terminating process...')
                        cleanup(None, None)

        except KeyboardInterrupt:
            pass
