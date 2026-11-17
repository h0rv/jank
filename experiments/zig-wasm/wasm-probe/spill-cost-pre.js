// AI-assisted: after instantiation/runtime setup, before main or jank initialization.
Module['preRun'] = [() => console.log('STARTUP ms=' + (process.uptime() * 1000))];
