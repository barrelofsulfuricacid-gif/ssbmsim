#include "ft/forward.h"
#include "pl/player.h"

#include <stdio.h>

static int check(int condition, const char* message)
{
    if (!condition) {
        fprintf(stderr, "native-player-mapping: %s\n", message);
        return 0;
    }
    return 1;
}

int main(void)
{
    Player_SetPlayerCharacter(0, CKIND_POPONANA);
    Player_SetSlottype(0, Gm_PKind_Human);
    if (!check(
            Player_8003248C(0, false) == Gm_PKind_Human,
            "Ice Climbers leader did not retain human control") ||
        !check(
            Player_8003248C(0, true) == Gm_PKind_Cpu,
            "Nana was not classified for source-owned CPU control") ||
        !check(
            Player_80032610(0, false) == FTKIND_POPO,
            "Ice Climbers leader mapping did not resolve to Popo") ||
        !check(
            Player_80032610(0, true) == FTKIND_NANA,
            "Ice Climbers companion mapping did not resolve to Nana")) {
        return 1;
    }

    Player_SetPlayerCharacter(0, CKIND_SEAK);
    if (!check(
            Player_8003248C(0, true) == Gm_PKind_Human,
            "Sheik transformation was misclassified as a CPU companion") ||
        !check(
            Player_80032610(0, true) == FTKIND_ZELDA,
            "Sheik transformation mapping did not resolve to Zelda")) {
        return 1;
    }

    puts("ssbm-native-player-mapping=pass");
    return 0;
}
