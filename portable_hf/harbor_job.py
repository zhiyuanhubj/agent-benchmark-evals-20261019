#!/usr/bin/env python3
"""Minimal original TB Harbor job entry; no scheduler/allocation dependency."""
import asyncio
import json
from pathlib import Path
import sys
from harbor.job import Job
from harbor.models.job.config import JobConfig

async def main():
    config=JobConfig.model_validate(json.loads(Path(sys.argv[1]).read_text()))
    job=await Job.create(config)
    result=await job.run()
    Path(sys.argv[1]).with_suffix('.result.json').write_text(result.model_dump_json(indent=2))

if __name__=='__main__':asyncio.run(main())
