using Shop.Contracts;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/admin/orders", () => new Order("demo", 0m));
app.Run();
