// AI-assisted example: borrow input/output only for the duration of this call.
export fn hello_weighted(values: ?[*]const i32, len: usize, out: ?*i64) c_int {
    const result = out orelse return 1;
    if (len != 0 and values == null) return 1;
    var total: i64 = 0;
    for (0..len) |index| {
        const weight: i64 = @intCast(index + 1);
        const product = @mulWithOverflow(@as(i64, values.?[index]), weight);
        if (product[1] != 0) return 2;
        const sum = @addWithOverflow(total, product[0]);
        if (sum[1] != 0) return 2;
        total = sum[0];
    }
    result.* = total;
    return 0;
}
