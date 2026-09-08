#include <stdio.h>

void fn_8016E730(void*);

typedef void (*MatchRoot)(void*);

static volatile MatchRoot match_root = fn_8016E730;

int main(void)
{
    if (match_root == NULL) {
        return 1;
    }
    puts("ssbm-match-root-link=pass");
    return 0;
}
