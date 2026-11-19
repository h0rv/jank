/* AI-assisted adapter for the unmodified host compiler's resource-dir API. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>

extern void jank_override_resource_dir(char const *);

static int (*jank_main)(int, char **, char **);

static int sdk_main(int argc, char **argv, char **env)
{
  char const *resources = getenv("JANK_RUNTIME_DIR");
  if(resources) { jank_override_resource_dir(resources); }
  return jank_main(argc, argv, env);
}

int __libc_start_main(int (*main_fn)(int, char **, char **), int argc, char **argv,
                      void (*init)(void), void (*fini)(void),
                      void (*rtld_fini)(void), void *stack_end)
{
  typedef int (*start_fn)(int (*)(int, char **, char **), int, char **,
                          void (*)(void), void (*)(void), void (*)(void), void *);
  start_fn start = (start_fn)dlsym(RTLD_NEXT, "__libc_start_main");
  jank_main = main_fn;
  return start(sdk_main, argc, argv, init, fini, rtld_fini, stack_end);
}
