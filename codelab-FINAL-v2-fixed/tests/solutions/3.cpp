#include <iostream>
using namespace std;
int main() {
    int n;
    cin >> n;
    long long f = 1;
    for (int i = 2; i <= n; i++) f *= i;
    cout << f;
    return 0;
}
