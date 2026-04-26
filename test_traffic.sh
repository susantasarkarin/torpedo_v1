#!/bin/bash
timeout 60 curl -v -b 'session_id=ImFkbWluIg.adX47Q.RyVRmAfNwbqpXCr6SRvZp4N5cWY' 'http://localhost:8000/api/traffic/dashboard-stats?days=7' 2>&1
