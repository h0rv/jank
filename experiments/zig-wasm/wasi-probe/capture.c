// AI-assisted prerequisite check, not a jank runtime test.
#include <errno.h>
#include <stdio.h>
#include <unistd.h>

int main(void) {
  errno = 0;
  int const copy = dup(STDOUT_FILENO);
  int const copy_error = errno;
  printf("WASI capture prerequisite: dup(1)=%d errno=%d (ENOTSUP=%d)\n",
         copy, copy_error, ENOTSUP);
  if (copy >= 0) close(copy);

  errno = 0;
  int const redirect = dup2(STDOUT_FILENO, STDOUT_FILENO);
  int const redirect_error = errno;
  printf("WASI capture prerequisite: dup2(1,1)=%d errno=%d (ENOTSUP=%d)\n",
         redirect, redirect_error, ENOTSUP);
  return !(copy == -1 && copy_error == ENOTSUP &&
           redirect == -1 && redirect_error == ENOTSUP);
}
