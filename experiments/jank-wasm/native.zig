const std = @import("std");

// Exported Zig functions use the C calling convention. No C source is needed.
export fn spike_add(a: i32, b: i32) i64 {
    return @as(i64, a) + @as(i64, b);
}

// The caller owns both buffers. Nothing is retained after the call.
// Status: 0 = success, 1 = null pointer, 2 = sum overflow.
// On failure, the output is unchanged. Null input is allowed for zero length.
// A non-null input must point to at least len aligned i32 values.
export fn spike_sum_i32(values: ?[*]const i32, len: usize, out: ?*i64) c_int {
    const result = out orelse return 1;
    if (len == 0) {
        result.* = 0;
        return 0;
    }
    const items = values orelse return 1;
    var sum: i64 = 0;
    for (items[0..len]) |value| {
        const next = @addWithOverflow(sum, @as(i64, value));
        if (next[1] != 0) return 2;
        sum = next[0];
    }
    result.* = sum;
    return 0;
}

test "add widens before addition" {
    try std.testing.expectEqual(@as(i64, 42), spike_add(20, 22));
    try std.testing.expectEqual(@as(i64, 4294967294), spike_add(2147483647, 2147483647));
    try std.testing.expectEqual(@as(i64, -4294967296), spike_add(-2147483648, -2147483648));
}

test "sum borrows a buffer and writes its result" {
    const values = [_]i32{ 10, -3, 20, 15 };
    var result: i64 = -1;
    try std.testing.expectEqual(@as(c_int, 0), spike_sum_i32(&values, values.len, &result));
    try std.testing.expectEqual(@as(i64, 42), result);
}

test "empty and invalid buffers have explicit outcomes" {
    var result: i64 = 99;
    try std.testing.expectEqual(@as(c_int, 1), spike_sum_i32(null, 1, &result));
    try std.testing.expectEqual(@as(i64, 99), result);
    try std.testing.expectEqual(@as(c_int, 1), spike_sum_i32(null, 0, null));
    try std.testing.expectEqual(@as(c_int, 0), spike_sum_i32(null, 0, &result));
    try std.testing.expectEqual(@as(i64, 0), result);
}
