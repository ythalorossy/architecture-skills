using Shop.Core;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton<OrderService>();
var app = builder.Build();
app.MapGet("/orders/{id}", (string id, OrderService orders) => orders.Place(id));
app.Run();
