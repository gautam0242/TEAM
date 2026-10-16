#include <iostream>
using namespace std;
void printFib(int n) {
    long long a = 0, b = 1;
    for (int i = 0; i < n; i++) {
        if (i) cout << " ";
        cout << a;
        long long t = a + b; a = b; b = t;
    }
}
int main() {
    int n;
    cin >> n;
    printFib(n);
    return 0;
}
